"""阶段九统一模型适配器的公共契约测试。"""

import asyncio
import hashlib
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import SecretStr

from app.domain.enums import ProviderType
from app.domain.grading import GradeResult, canonical_json_bytes
from app.grading.prompt import GradingPrompt, PromptMessage
from app.providers.anthropic import AnthropicAdapter
from app.providers.base import (
    ProviderAdapterBase,
    ProviderAdapterError,
    ProviderAdapterHttpClient,
    ProviderGradeRequest,
    ProviderHttpResponse,
    ProviderModelCapabilities,
    ProviderPricing,
    ProviderTokenPriceTier,
    ProviderTokenUsage,
    raise_for_provider_status,
)
from app.providers.connection import HostResolver, ProviderBaseUrlPolicy
from app.providers.deepseek import DeepSeekAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.glm import GlmAdapter
from app.providers.kimi import KimiAdapter
from app.providers.openai import OpenAIAdapter
from app.providers.openai_compatible import OpenAICompatibleAdapter


class PublicDeepSeekResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("api.deepseek.com", 443)
        return ("8.8.8.8",)


class PostOnlyProviderClient:
    async def get_json(self, **kwargs: object) -> ProviderHttpResponse:
        raise AssertionError("该测试只允许 POST")


class SuccessfulDeepSeekClient(PostOnlyProviderClient):
    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-stage-nine",
                "object": "chat.completion",
                "created": 1784200000,
                "model": "teacher-configured-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"schema_version":"grade-result.v1"}',
                            "reasoning_content": None,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_cache_hit_tokens": 25,
                    "prompt_cache_miss_tokens": 75,
                },
            },
            raw_body=b'{"id":"chatcmpl-stage-nine"}',
        )


class PublicOpenAIResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("api.openai.com", 443)
        return ("8.8.8.8",)


class SuccessfulOpenAIClient(PostOnlyProviderClient):
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "resp-stage-nine",
                "object": "response",
                "status": "completed",
                "model": "teacher-configured-openai-model",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"schema_version":"grade-result.v1"}',
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 25},
                    "output_tokens": 30,
                    "output_tokens_details": {"reasoning_tokens": 10},
                    "total_tokens": 130,
                },
            },
            raw_body=b'{"id":"resp-stage-nine"}',
        )


class PublicAnthropicResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("api.anthropic.com", 443)
        return ("8.8.8.8",)


class SuccessfulAnthropicClient(PostOnlyProviderClient):
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "msg-stage-nine",
                "type": "message",
                "role": "assistant",
                "model": "teacher-configured-anthropic-model",
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": '{"schema_version":"grade-result.v1"}',
                    }
                ],
                "usage": {
                    "input_tokens": 70,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 20,
                    "output_tokens": 30,
                },
            },
            raw_body=b'{"id":"msg-stage-nine"}',
        )


class PublicGeminiResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("generativelanguage.googleapis.com", 443)
        return ("8.8.8.8",)


class SuccessfulGeminiClient(PostOnlyProviderClient):
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None
        self.url: str | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        self.url = kwargs["url"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "responseId": "gemini-stage-nine",
                "modelVersion": "teacher-configured-gemini-model",
                "candidates": [
                    {
                        "index": 0,
                        "finishReason": "STOP",
                        "content": {
                            "role": "model",
                            "parts": [{"text": '{"schema_version":"grade-result.v1"}'}],
                        },
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "cachedContentTokenCount": 25,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 10,
                    "totalTokenCount": 130,
                },
            },
            raw_body=b'{"responseId":"gemini-stage-nine"}',
        )


class PublicCompatibleResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("models.example.edu", 443)
        return ("8.8.8.8",)


class SuccessfulCompatibleClient(PostOnlyProviderClient):
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-compatible-stage-nine",
                "object": "chat.completion",
                "model": "configured-compatible-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"schema_version":"grade-result.v1"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
            raw_body=b'{"id":"chatcmpl-compatible-stage-nine"}',
        )


class PublicKimiResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("api.moonshot.cn", 443)
        return ("8.8.8.8",)


class SuccessfulKimiClient(PostOnlyProviderClient):
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-kimi-stage-nine",
                "object": "chat.completion",
                "model": "teacher-configured-kimi-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"schema_version":"grade-result.v1"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_tokens_details": {"cached_tokens": 25},
                },
            },
            raw_body=b'{"id":"chatcmpl-kimi-stage-nine"}',
        )


class PublicGlmResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert (host, port) == ("open.bigmodel.cn", 443)
        return ("8.8.8.8",)


class SuccessfulGlmClient(PostOnlyProviderClient):
    def __init__(self) -> None:
        self.request_body: dict[str, object] | None = None

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.request_body = kwargs["json_body"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-glm-stage-nine",
                "object": "chat.completion",
                "model": "teacher-configured-glm-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"schema_version":"grade-result.v1"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
            raw_body=b'{"id":"chatcmpl-glm-stage-nine"}',
        )


class AnyPublicResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        assert host and port == 443
        return ("8.8.8.8",)


class FailureClient(PostOnlyProviderClient):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=self.status_code,
            json_body={"error": {"message": "upstream-secret-error-body"}},
            raw_body=b'{"error":{"message":"upstream-secret-error-body"}}',
        )


class DeepSeekFinishReasonClient(PostOnlyProviderClient):
    def __init__(self, finish_reason: str) -> None:
        self.finish_reason = finish_reason

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-stage-nine",
                "object": "chat.completion",
                "model": "teacher-configured-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": self.finish_reason,
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": None,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 100,
                },
            },
            raw_body=b'{"id":"chatcmpl-stage-nine"}',
        )


class CompatibleFinishReasonClient(PostOnlyProviderClient):
    def __init__(self, finish_reason: str) -> None:
        self.finish_reason = finish_reason

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-compatible-stage-nine",
                "object": "chat.completion",
                "model": "configured-compatible-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": self.finish_reason,
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
            raw_body=b'{"id":"chatcmpl-compatible-stage-nine"}',
        )


class OpenAIFinishClient(PostOnlyProviderClient):
    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        payload: dict[str, object] = {
            "id": "resp-stage-nine",
            "object": "response",
            "model": "teacher-configured-openai-model",
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 20,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 120,
            },
        }
        if self.mode == "truncated":
            payload.update(
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                }
            )
        else:
            payload.update(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "refusal", "refusal": "cannot comply"}],
                        }
                    ],
                }
            )
        return ProviderHttpResponse(
            status_code=200,
            json_body=payload,
            raw_body=b'{"id":"resp-stage-nine"}',
        )


class AnthropicFinishClient(PostOnlyProviderClient):
    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "msg-stage-nine",
                "type": "message",
                "role": "assistant",
                "model": "teacher-configured-anthropic-model",
                "stop_reason": self.stop_reason,
                "content": [],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
            raw_body=b'{"id":"msg-stage-nine"}',
        )


class GeminiFinishClient(PostOnlyProviderClient):
    def __init__(self, finish_reason: str) -> None:
        self.finish_reason = finish_reason

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "responseId": "gemini-stage-nine",
                "modelVersion": "teacher-configured-gemini-model",
                "candidates": [
                    {
                        "index": 0,
                        "finishReason": self.finish_reason,
                        "content": {"role": "model", "parts": []},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 20,
                    "totalTokenCount": 120,
                },
            },
            raw_body=b'{"responseId":"gemini-stage-nine"}',
        )


class SlowProviderClient(PostOnlyProviderClient):
    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        await asyncio.sleep(0.05)
        return await SuccessfulDeepSeekClient().post_json(**kwargs)


class KimiQuotaClient(PostOnlyProviderClient):
    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=429,
            json_body={
                "error": {
                    "type": "exceeded_current_quota_error",
                    "code": "exceeded_current_quota_error",
                    "message": "not returned to caller",
                }
            },
            raw_body=b'{"error":{"code":"exceeded_current_quota_error"}}',
        )


class DeepSeekModelListClient:
    def __init__(self) -> None:
        self.url: str | None = None

    async def get_json(self, **kwargs: object) -> ProviderHttpResponse:
        self.url = kwargs["url"]  # type: ignore[assignment]
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "object": "list",
                "data": [
                    {
                        "id": "teacher-configured-model",
                        "object": "model",
                        "owned_by": "deepseek",
                    }
                ],
            },
            raw_body=b'{"object":"list"}',
        )

    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        raise AssertionError("支持 Models API 时不应发送计费评分请求")


def grading_prompt() -> GradingPrompt:
    digest = b"a" * 32
    schema = result_schema_json()
    return GradingPrompt(
        prompt_hash=digest,
        result_schema_hash=hashlib.sha256(schema).digest(),
        rubric_hash=digest,
        request_version="grade-request.v1",
        base_request_hash=digest,
        call_hash=digest,
        messages=(
            PromptMessage(role="system", content="Return the required JSON object."),
            PromptMessage(role="user", content='{"operation":"grade_submission"}'),
        ),
    )


def result_schema_json() -> bytes:
    return canonical_json_bytes(GradeResult.model_json_schema(mode="validation"))


def deepseek_capabilities(*, pricing: ProviderPricing | None = None) -> ProviderModelCapabilities:
    return ProviderModelCapabilities(
        capability_version="test-capabilities.v1",
        model="teacher-configured-model",
        context_window_tokens=128_000,
        max_output_tokens=8192,
        structured_output="json_object",
        schema_dialect="canonical",
        sampling_policy="temperature_zero",
        thinking_policy="disabled",
        output_token_parameter="max_tokens",
        supports_model_listing=True,
        pricing=pricing,
    )


def deepseek_request(*, pricing: ProviderPricing | None = None) -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000009"),
        config_version=3,
        provider_type=ProviderType.DEEPSEEK,
        base_url="https://api.deepseek.com",
        api_key=SecretStr("secret-canary"),
        model="teacher-configured-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=deepseek_capabilities(pricing=pricing),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


def openai_request() -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000010"),
        config_version=2,
        provider_type=ProviderType.OPENAI,
        base_url="https://api.openai.com/v1",
        api_key=SecretStr("secret-canary"),
        model="teacher-configured-openai-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=ProviderModelCapabilities(
            capability_version="test-capabilities.v1",
            model="teacher-configured-openai-model",
            context_window_tokens=128_000,
            max_output_tokens=8192,
            structured_output="json_schema",
            schema_dialect="openai",
            sampling_policy="omit",
            thinking_policy="omit",
            output_token_parameter="max_output_tokens",
            supports_model_listing=True,
        ),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


def anthropic_request() -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000011"),
        config_version=1,
        provider_type=ProviderType.ANTHROPIC,
        base_url="https://api.anthropic.com",
        api_key=SecretStr("secret-canary"),
        model="teacher-configured-anthropic-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=ProviderModelCapabilities(
            capability_version="test-capabilities.v1",
            model="teacher-configured-anthropic-model",
            context_window_tokens=200_000,
            max_output_tokens=8192,
            structured_output="json_schema",
            schema_dialect="anthropic",
            sampling_policy="omit",
            thinking_policy="omit",
            output_token_parameter="max_tokens",
            supports_model_listing=True,
        ),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


def gemini_request() -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000012"),
        config_version=1,
        provider_type=ProviderType.GEMINI,
        base_url="https://generativelanguage.googleapis.com",
        api_key=SecretStr("secret-canary"),
        model="teacher-configured-gemini-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=ProviderModelCapabilities(
            capability_version="test-capabilities.v1",
            model="teacher-configured-gemini-model",
            context_window_tokens=1_000_000,
            max_output_tokens=65_536,
            structured_output="json_schema",
            schema_dialect="gemini",
            sampling_policy="omit",
            thinking_policy="omit",
            output_token_parameter="max_output_tokens",
            supports_model_listing=True,
        ),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


def compatible_request() -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000013"),
        config_version=4,
        provider_type=ProviderType.OPENAI_COMPATIBLE,
        base_url="https://models.example.edu/v1",
        api_key=SecretStr("secret-canary"),
        model="configured-compatible-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=ProviderModelCapabilities(
            capability_version="admin-confirmed.v1",
            model="configured-compatible-model",
            context_window_tokens=64_000,
            max_output_tokens=8192,
            structured_output="json_object",
            schema_dialect="canonical",
            sampling_policy="omit",
            thinking_policy="omit",
            output_token_parameter="max_tokens",
            supports_model_listing=False,
        ),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


def kimi_request() -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000014"),
        config_version=1,
        provider_type=ProviderType.KIMI,
        base_url="https://api.moonshot.cn/v1",
        api_key=SecretStr("secret-canary"),
        model="teacher-configured-kimi-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=ProviderModelCapabilities(
            capability_version="admin-confirmed.v1",
            model="teacher-configured-kimi-model",
            context_window_tokens=256_000,
            max_output_tokens=8192,
            structured_output="json_object",
            schema_dialect="canonical",
            sampling_policy="omit",
            thinking_policy="disabled",
            output_token_parameter="max_completion_tokens",
            supports_model_listing=True,
        ),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


def glm_request() -> ProviderGradeRequest:
    return ProviderGradeRequest(
        provider_config_id=UUID("00000000-0000-0000-0000-000000000015"),
        config_version=1,
        provider_type=ProviderType.GLM,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key=SecretStr("secret-canary"),
        model="teacher-configured-glm-model",
        timeout_seconds=Decimal("60"),
        max_output_tokens=4096,
        capabilities=ProviderModelCapabilities(
            capability_version="admin-confirmed.v1",
            model="teacher-configured-glm-model",
            context_window_tokens=128_000,
            max_output_tokens=8192,
            structured_output="json_object",
            schema_dialect="canonical",
            sampling_policy="do_sample_false",
            thinking_policy="disabled",
            output_token_parameter="max_tokens",
            supports_model_listing=False,
        ),
        result_schema_json=result_schema_json(),
        prompt=grading_prompt(),
    )


@pytest.mark.anyio
async def test_deepseek_grades_through_the_unified_adapter_interface() -> None:
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
        http_client=SuccessfulDeepSeekClient(),
    )

    result = await adapter.grade(deepseek_request())

    assert result.output_text == '{"schema_version":"grade-result.v1"}'


@pytest.mark.anyio
async def test_deepseek_normalizes_standard_and_cached_token_usage() -> None:
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
        http_client=SuccessfulDeepSeekClient(),
    )

    result = await adapter.grade(deepseek_request())

    assert result.usage.model_dump() == {
        "input_tokens": 100,
        "cached_input_tokens": 25,
        "cache_write_input_tokens": 0,
        "output_tokens": 20,
        "reasoning_tokens": 0,
        "total_tokens": 120,
    }


def test_deepseek_estimates_cost_from_an_explicit_pricing_snapshot() -> None:
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
        http_client=SuccessfulDeepSeekClient(),
    )
    pricing = ProviderPricing(
        tariff_version="test-price-2026-07-16",
        currency="USD",
        tiers=(
            ProviderTokenPriceTier(
                input_per_million=Decimal("1"),
                cache_read_per_million=Decimal("0.25"),
                cache_write_per_million=Decimal("1"),
                output_per_million=Decimal("2"),
            ),
        ),
    )

    estimate = adapter.estimate_cost(
        usage=ProviderTokenUsage(
            input_tokens=100,
            cached_input_tokens=25,
            cache_write_input_tokens=0,
            output_tokens=20,
            reasoning_tokens=0,
            total_tokens=120,
        ),
        pricing=pricing,
    )

    assert estimate is not None
    assert estimate.amount == Decimal("0.00012125")


@pytest.mark.anyio
async def test_openai_responses_adapter_sends_strict_schema_without_sampling_overrides() -> None:
    http_client = SuccessfulOpenAIClient()
    adapter = OpenAIAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicOpenAIResolver()),
        http_client=http_client,
    )

    result = await adapter.grade(openai_request())

    assert result.output_text == '{"schema_version":"grade-result.v1"}'
    assert http_client.request_body is not None
    assert http_client.request_body["store"] is False
    assert http_client.request_body["max_output_tokens"] == 4096
    assert "temperature" not in http_client.request_body
    text_config = http_client.request_body["text"]
    assert isinstance(text_config, dict)
    assert text_config["format"]["type"] == "json_schema"
    assert text_config["format"]["strict"] is True


@pytest.mark.anyio
async def test_anthropic_messages_adapter_uses_output_format_and_default_sampling() -> None:
    http_client = SuccessfulAnthropicClient()
    adapter = AnthropicAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicAnthropicResolver()),
        http_client=http_client,
    )

    result = await adapter.grade(anthropic_request())

    assert result.output_text == '{"schema_version":"grade-result.v1"}'
    assert result.usage.input_tokens == 100
    assert result.usage.cache_write_input_tokens == 10
    assert result.usage.cached_input_tokens == 20
    assert http_client.request_body is not None
    assert http_client.request_body["max_tokens"] == 4096
    assert "temperature" not in http_client.request_body
    assert "thinking" not in http_client.request_body
    output_config = http_client.request_body["output_config"]
    assert isinstance(output_config, dict)
    assert output_config["format"]["type"] == "json_schema"


@pytest.mark.anyio
async def test_gemini_generate_content_adapter_uses_schema_without_sampling_overrides() -> None:
    http_client = SuccessfulGeminiClient()
    adapter = GeminiAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicGeminiResolver()),
        http_client=http_client,
    )

    result = await adapter.grade(gemini_request())

    assert result.output_text == '{"schema_version":"grade-result.v1"}'
    assert result.usage.output_tokens == 30
    assert result.usage.reasoning_tokens == 10
    assert http_client.url is not None and http_client.url.endswith(
        "/v1beta/models/teacher-configured-gemini-model:generateContent"
    )
    assert http_client.request_body is not None
    generation_config = http_client.request_body["generationConfig"]
    assert isinstance(generation_config, dict)
    assert generation_config["maxOutputTokens"] == 4096
    assert "temperature" not in generation_config
    assert "thinkingConfig" not in generation_config
    assert generation_config["responseFormat"]["text"]["mimeType"] == "application/json"


@pytest.mark.anyio
async def test_generic_compatible_adapter_obeys_explicit_capabilities_without_guessing() -> None:
    http_client = SuccessfulCompatibleClient()
    adapter = OpenAICompatibleAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicCompatibleResolver()),
        http_client=http_client,
    )

    result = await adapter.grade(compatible_request())

    assert result.output_text == '{"schema_version":"grade-result.v1"}'
    assert http_client.request_body is not None
    assert http_client.request_body["max_tokens"] == 4096
    assert http_client.request_body["response_format"] == {"type": "json_object"}
    assert "temperature" not in http_client.request_body
    assert "thinking" not in http_client.request_body


@pytest.mark.anyio
async def test_kimi_adapter_uses_model_profile_without_forcing_temperature_zero() -> None:
    http_client = SuccessfulKimiClient()
    adapter = KimiAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicKimiResolver()),
        http_client=http_client,
    )

    result = await adapter.grade(kimi_request())

    assert result.provider_type.value == "kimi"
    assert result.usage.cached_input_tokens == 25
    assert http_client.request_body is not None
    assert http_client.request_body["max_completion_tokens"] == 4096
    assert "max_tokens" not in http_client.request_body
    assert "temperature" not in http_client.request_body
    assert http_client.request_body["thinking"] == {"type": "disabled"}


@pytest.mark.anyio
async def test_glm_adapter_uses_deterministic_sampling_without_claiming_models_api() -> None:
    http_client = SuccessfulGlmClient()
    adapter = GlmAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicGlmResolver()),
        http_client=http_client,
    )

    result = await adapter.grade(glm_request())

    assert result.provider_type.value == "glm"
    assert http_client.request_body is not None
    assert http_client.request_body["do_sample"] is False
    assert "temperature" not in http_client.request_body
    assert http_client.request_body["thinking"] == {"type": "disabled"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("adapter_type", "request_factory"),
    [
        (DeepSeekAdapter, deepseek_request),
        (KimiAdapter, kimi_request),
        (GlmAdapter, glm_request),
        (OpenAIAdapter, openai_request),
        (AnthropicAdapter, anthropic_request),
        (GeminiAdapter, gemini_request),
        (OpenAICompatibleAdapter, compatible_request),
    ],
)
async def test_all_adapters_classify_authentication_failures_without_leaking_upstream_body(
    adapter_type: type[object],
    request_factory: object,
) -> None:
    adapter = adapter_type(  # type: ignore[call-arg]
        url_policy=ProviderBaseUrlPolicy(resolver=AnyPublicResolver()),
        http_client=FailureClient(401),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(request_factory())  # type: ignore[attr-defined,operator]

    assert raised.value.code == "provider_authentication_failed"
    assert "upstream-secret-error-body" not in str(raised.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("adapter_type", "request_factory", "client_type", "resolver_type"),
    [
        (
            DeepSeekAdapter,
            deepseek_request,
            SuccessfulDeepSeekClient,
            PublicDeepSeekResolver,
        ),
        (KimiAdapter, kimi_request, SuccessfulKimiClient, PublicKimiResolver),
        (GlmAdapter, glm_request, SuccessfulGlmClient, PublicGlmResolver),
        (OpenAIAdapter, openai_request, SuccessfulOpenAIClient, PublicOpenAIResolver),
        (
            AnthropicAdapter,
            anthropic_request,
            SuccessfulAnthropicClient,
            PublicAnthropicResolver,
        ),
        (GeminiAdapter, gemini_request, SuccessfulGeminiClient, PublicGeminiResolver),
        (
            OpenAICompatibleAdapter,
            compatible_request,
            SuccessfulCompatibleClient,
            PublicCompatibleResolver,
        ),
    ],
)
async def test_all_suppliers_return_the_same_auditable_result_contract(
    adapter_type: Callable[..., ProviderAdapterBase],
    request_factory: Callable[[], ProviderGradeRequest],
    client_type: Callable[[], ProviderAdapterHttpClient],
    resolver_type: Callable[[], HostResolver],
) -> None:
    request = request_factory()
    adapter = adapter_type(
        url_policy=ProviderBaseUrlPolicy(resolver=resolver_type()),
        http_client=client_type(),
    )

    result = await adapter.grade(request)

    assert result.provider_type is request.provider_type
    assert result.requested_model == request.model
    assert result.reported_model
    assert result.request_id
    assert result.output_text
    assert result.usage.input_tokens >= 0
    assert result.usage.output_tokens >= 0
    assert result.raw_response_sha256 == hashlib.sha256(result.raw_response).digest()
    assert len(result.sent_schema_sha256) == 32


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("finish_reason", "expected_code"),
    [
        ("length", "provider_output_truncated"),
        ("content_filter", "provider_content_refused"),
    ],
)
async def test_deepseek_classifies_truncation_and_refusal(
    finish_reason: str,
    expected_code: str,
) -> None:
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
        http_client=DeepSeekFinishReasonClient(finish_reason),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(deepseek_request())

    assert raised.value.code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("finish_reason", "expected_code"),
    [
        ("length", "provider_output_truncated"),
        ("content_filter", "provider_content_refused"),
    ],
)
async def test_chat_completions_adapters_classify_truncation_and_refusal(
    finish_reason: str,
    expected_code: str,
) -> None:
    adapter = OpenAICompatibleAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicCompatibleResolver()),
        http_client=CompatibleFinishReasonClient(finish_reason),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(compatible_request())

    assert raised.value.code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("truncated", "provider_output_truncated"),
        ("refused", "provider_content_refused"),
    ],
)
async def test_openai_classifies_incomplete_and_refusal_outputs(
    mode: str,
    expected_code: str,
) -> None:
    adapter = OpenAIAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicOpenAIResolver()),
        http_client=OpenAIFinishClient(mode),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(openai_request())

    assert raised.value.code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stop_reason", "expected_code"),
    [
        ("max_tokens", "provider_output_truncated"),
        ("refusal", "provider_content_refused"),
    ],
)
async def test_anthropic_classifies_truncation_and_refusal(
    stop_reason: str,
    expected_code: str,
) -> None:
    adapter = AnthropicAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicAnthropicResolver()),
        http_client=AnthropicFinishClient(stop_reason),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(anthropic_request())

    assert raised.value.code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("finish_reason", "expected_code"),
    [
        ("MAX_TOKENS", "provider_output_truncated"),
        ("SAFETY", "provider_content_refused"),
    ],
)
async def test_gemini_classifies_truncation_and_safety_refusal(
    finish_reason: str,
    expected_code: str,
) -> None:
    adapter = GeminiAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicGeminiResolver()),
        http_client=GeminiFinishClient(finish_reason),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(gemini_request())

    assert raised.value.code == expected_code


@pytest.mark.anyio
async def test_adapter_deadline_covers_the_complete_provider_call() -> None:
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
        http_client=SlowProviderClient(),
    )
    request = deepseek_request().model_copy(update={"timeout_seconds": Decimal("0.001")})

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(request)

    assert raised.value.code == "provider_timeout"
    assert raised.value.retryable
    assert raised.value.retry_safety == "unknown"


@pytest.mark.anyio
async def test_credential_validation_uses_models_api_when_capability_enables_it() -> None:
    http_client = DeepSeekModelListClient()
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
        http_client=http_client,
    )

    validation = await adapter.validate_credentials(deepseek_request())

    assert validation.model == "teacher-configured-model"
    assert validation.method == "models"
    assert validation.request_id is None
    assert validation.billable is False
    assert http_client.url == "https://api.deepseek.com/models"


@pytest.mark.anyio
async def test_credential_validation_uses_billable_smoke_when_models_api_is_disabled() -> None:
    adapter = GlmAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicGlmResolver()),
        http_client=SuccessfulGlmClient(),
    )

    validation = await adapter.validate_credentials(glm_request())

    assert validation.model == "teacher-configured-glm-model"
    assert validation.method == "smoke"
    assert validation.request_id == "chatcmpl-glm-stage-nine"
    assert validation.billable is True


@pytest.mark.anyio
async def test_kimi_quota_exhaustion_is_not_misclassified_as_retryable_rate_limit() -> None:
    adapter = KimiAdapter(
        url_policy=ProviderBaseUrlPolicy(resolver=PublicKimiResolver()),
        http_client=KimiQuotaClient(),
    )

    with pytest.raises(ProviderAdapterError) as raised:
        await adapter.grade(kimi_request())

    assert raised.value.code == "provider_quota_exhausted"
    assert not raised.value.retryable


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (408, "provider_timeout"),
        (429, "provider_rate_limited"),
        (503, "provider_unavailable"),
    ],
)
def test_shared_http_failures_have_stable_retryable_classification(
    status_code: int,
    expected_code: str,
) -> None:
    response = ProviderHttpResponse(
        status_code=status_code,
        json_body={"error": "sensitive upstream detail"},
        raw_body=b'{"error":"sensitive upstream detail"}',
    )

    with pytest.raises(ProviderAdapterError) as raised:
        raise_for_provider_status(response, provider_type=ProviderType.DEEPSEEK)

    assert raised.value.code == expected_code
    assert raised.value.retryable
    assert raised.value.retry_safety == "safe"
    assert "sensitive upstream detail" not in str(raised.value)


def test_provider_snapshot_hash_locks_prompt_template_but_allows_the_unique_correction() -> None:
    request = deepseek_request()
    correction_prompt = request.prompt.model_copy(
        update={
            "call_hash": b"b" * 32,
            "messages": (
                *request.prompt.messages,
                PromptMessage(role="user", content='{"operation":"correct_grade_output"}'),
            ),
        }
    )
    correction_request = request.model_copy(update={"prompt": correction_prompt})
    changed_template = request.model_copy(
        update={
            "prompt": request.prompt.model_copy(update={"prompt_hash": b"c" * 32}),
        }
    )
    changed_config = request.model_copy(update={"config_version": request.config_version + 1})

    assert correction_request.snapshot_hash() == request.snapshot_hash()
    assert changed_template.snapshot_hash() != request.snapshot_hash()
    assert changed_config.snapshot_hash() != request.snapshot_hash()
