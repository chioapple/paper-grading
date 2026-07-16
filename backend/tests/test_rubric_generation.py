"""结构化 Rubric 外部生成边界测试。"""

import asyncio
import json
from copy import deepcopy
from decimal import Decimal

import pytest

from app.domain.enums import ProviderType
from app.providers.connection import ProviderBaseUrlPolicy, ProviderHttpResponse
from app.rubrics.generation import (
    OpenAICompatibleRubricGenerator,
    RubricGenerationError,
    RubricGenerationRequest,
)


class PublicResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("api.deepseek.com", 443)
        return ("8.8.8.8",)


def valid_rubric_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "total_score": "100",
        "score_step": "1",
        "dimensions": [
            {
                "id": "thesis",
                "name": "Thesis",
                "description": "Quality of the central claim.",
                "max_score": "100",
                "bands": [
                    {
                        "label": "Not demonstrated",
                        "min_score": "0",
                        "max_score": "0",
                        "description": "No defensible thesis.",
                    },
                    {
                        "label": "Demonstrated",
                        "min_score": "1",
                        "max_score": "100",
                        "description": "A defensible thesis is present.",
                    },
                ],
                "evidence_requirements": ["Quote the thesis statement."],
            }
        ],
        "deductions": [],
    }


def valid_provider_response() -> dict[str, object]:
    return {
        "id": "chatcmpl-stage-six",
        "object": "chat.completion",
        "created": 1784170800,
        "model": "deepseek-chat",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(valid_rubric_payload()),
                    "reasoning_content": None,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 80,
            "completion_tokens": 120,
            "total_tokens": 200,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 80,
        },
    }


def generation_request() -> RubricGenerationRequest:
    return RubricGenerationRequest(
        provider_type="deepseek",
        base_url="https://api.deepseek.com",
        api_key="secret-canary",
        model="deepseek-chat",
        timeout_seconds="60",
        assignment_title="Argumentative Essay",
        assignment_instructions="Write 800 words with evidence.",
        original_rubric="Thesis: 100 points.",
        total_score=Decimal("100"),
        score_step=Decimal("1"),
    )


class SuccessfulRubricHttpClient:
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body=valid_provider_response(),
        )


@pytest.mark.anyio
async def test_openai_compatible_response_is_strictly_validated_as_a_structured_rubric() -> None:
    http_client = SuccessfulRubricHttpClient()
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=http_client,
    )

    result = await generator.generate(generation_request())

    assert result.total_score == Decimal("100")
    assert result.dimensions[0].id == "thesis"
    assert http_client.request_body is not None
    assert http_client.request_body["model"] == "deepseek-chat"
    assert http_client.request_body["response_format"] == {"type": "json_object"}
    assert http_client.request_body["temperature"] == 0
    assert http_client.request_body["max_tokens"] == 16_384
    assert http_client.request_body["thinking"] == {"type": "disabled"}


class FixedRubricHttpClient:
    def __init__(self, response: ProviderHttpResponse) -> None:
        self.response = response

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return self.response


class CapturingFixedRubricHttpClient(FixedRubricHttpClient):
    def __init__(self, response: ProviderHttpResponse) -> None:
        super().__init__(response)
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return self.response


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ({"object": "text_completion"}, "rubric_provider_response_invalid"),
        ({"model": "another-model"}, "rubric_provider_response_invalid"),
        ({"choices": []}, "rubric_provider_response_invalid"),
        (
            {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {
                            "role": "assistant",
                            "content": "{}",
                            "reasoning_content": None,
                        },
                    }
                ]
            },
            "rubric_provider_output_truncated",
        ),
        (
            {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "content_filter",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": None,
                        },
                    }
                ]
            },
            "rubric_provider_content_filtered",
        ),
        (
            {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "  ",
                            "reasoning_content": None,
                        },
                    }
                ]
            },
            "rubric_provider_response_invalid",
        ),
        (
            {
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": -1,
                    "total_tokens": 79,
                }
            },
            "rubric_provider_response_invalid",
        ),
    ],
)
async def test_chat_completion_envelope_is_validated_before_rubric_content(
    mutation: dict[str, object],
    expected_code: str,
) -> None:
    response = deepcopy(valid_provider_response())
    response.update(mutation)
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=FixedRubricHttpClient(
            ProviderHttpResponse(status_code=200, json_body=response)
        ),
    )

    with pytest.raises(RubricGenerationError) as raised:
        await generator.generate(generation_request())

    assert raised.value.code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, "rubric_provider_request_invalid"),
        (402, "rubric_provider_balance_unavailable"),
        (422, "rubric_provider_request_invalid"),
        (429, "rubric_provider_rate_limited"),
        (503, "rubric_provider_unavailable"),
    ],
)
async def test_provider_http_failures_use_stable_codes_without_exposing_the_body(
    status_code: int,
    expected_code: str,
) -> None:
    canary = "upstream-secret-error-body"
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=FixedRubricHttpClient(
            ProviderHttpResponse(
                status_code=status_code,
                json_body={"error": {"message": canary}},
            )
        ),
    )

    with pytest.raises(RubricGenerationError) as raised:
        await generator.generate(generation_request())

    assert raised.value.code == expected_code
    assert canary not in str(raised.value)


@pytest.mark.anyio
async def test_empty_success_response_is_rejected_explicitly() -> None:
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=FixedRubricHttpClient(ProviderHttpResponse(status_code=200, json_body={})),
    )

    with pytest.raises(RubricGenerationError) as raised:
        await generator.generate(generation_request())

    assert raised.value.code == "rubric_provider_response_invalid"


class OpenAiPublicResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("api.openai.com", 443)
        return ("8.8.8.8",)


@pytest.mark.anyio
async def test_thinking_parameter_is_not_sent_to_other_openai_compatible_providers() -> None:
    response = valid_provider_response()
    response["model"] = "gpt-4.1"
    response.pop("usage")
    http_client = CapturingFixedRubricHttpClient(
        ProviderHttpResponse(status_code=200, json_body=response)
    )
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=OpenAiPublicResolver()),
        http_client=http_client,
    )
    request = generation_request().model_copy(
        update={
            "provider_type": ProviderType.OPENAI,
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4.1",
        }
    )

    result = await generator.generate(request)

    assert result.total_score == Decimal("100")
    assert http_client.request_body is not None
    assert "thinking" not in http_client.request_body


class KeepAliveLikeSlowHttpClient:
    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        await asyncio.sleep(0.05)
        return ProviderHttpResponse(
            status_code=200,
            json_body=valid_provider_response(),
        )


@pytest.mark.anyio
async def test_generation_has_one_wall_clock_deadline_around_the_whole_http_call() -> None:
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=KeepAliveLikeSlowHttpClient(),
    )
    request = generation_request().model_copy(update={"timeout_seconds": Decimal("0.001")})

    with pytest.raises(RubricGenerationError) as raised:
        await generator.generate(request)

    assert raised.value.code == "rubric_provider_timeout"


class MarkdownWrappedRubricHttpClient:
    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "choices": [{"message": {"content": '```json\n{"schema_version": 1}\n```'}}]
            },
        )


@pytest.mark.anyio
async def test_invalid_provider_json_is_rejected_without_fence_stripping_or_repair() -> None:
    generator = OpenAICompatibleRubricGenerator(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicResolver()),
        http_client=MarkdownWrappedRubricHttpClient(),
    )

    with pytest.raises(
        RubricGenerationError,
        match="没有返回有效的结构化评分标准",
    ):
        await generator.generate(
            RubricGenerationRequest(
                provider_type="deepseek",
                base_url="https://api.deepseek.com",
                api_key="secret-canary",
                model="deepseek-chat",
                timeout_seconds="60",
                assignment_title="Argumentative Essay",
                assignment_instructions="Write 800 words with evidence.",
                original_rubric="Thesis: 100 points.",
                total_score="100",
                score_step="1",
            )
        )
