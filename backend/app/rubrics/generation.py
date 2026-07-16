"""使用 OpenAI-compatible 接口生成结构化 Rubric。"""

import asyncio
import json
import ssl
from decimal import Decimal
from typing import Protocol

import certifi
from httpcore import AsyncConnectionPool, NetworkError, ProtocolError, TimeoutException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.domain.enums import ProviderType
from app.domain.rubric import StructuredRubric
from app.providers.connection import (
    PinnedNetworkBackend,
    ProviderBaseUrlPolicy,
    ProviderHttpResponse,
    ValidatedBaseUrl,
)

OPENAI_COMPATIBLE_PROVIDER_TYPES = {
    ProviderType.DEEPSEEK,
    ProviderType.KIMI,
    ProviderType.GLM,
    ProviderType.OPENAI,
    ProviderType.OPENAI_COMPATIBLE,
}
MAX_RUBRIC_OUTPUT_TOKENS = 16_384


class RubricGenerationError(RuntimeError):
    """生成失败；只携带稳定错误码和安全说明。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RubricGenerationRequest(BaseModel):
    """一次 Rubric 转换所需的固定输入快照。"""

    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    base_url: str
    api_key: SecretStr = Field(repr=False, min_length=1)
    model: str = Field(min_length=1)
    timeout_seconds: Decimal = Field(gt=0, le=300)
    assignment_title: str = Field(min_length=1, max_length=300)
    assignment_instructions: str = Field(min_length=1, max_length=100_000)
    original_rubric: str = Field(min_length=1, max_length=100_000)
    total_score: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    score_step: Decimal = Field(gt=0, max_digits=10, decimal_places=4)


class RubricHttpClient(Protocol):
    """外部 HTTP 是生成流程唯一可替换的网络边界。"""

    async def post_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse: ...


class RubricGenerator(Protocol):
    """结构化生成公开接口。"""

    async def generate(self, request: RubricGenerationRequest) -> StructuredRubric: ...


MAX_RUBRIC_RESPONSE_BYTES = 1_000_000


class HttpCoreRubricClient:
    """禁用代理和重定向、固定公网 IP 的真实生成客户端。"""

    async def post_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse:
        timeout = float(timeout_seconds)
        raw_request = json.dumps(
            json_body,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        pool = AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=PinnedNetworkBackend(target),
        )
        try:
            try:
                async with pool.stream(
                    "POST",
                    url,
                    headers=list(headers.items()),
                    content=raw_request,
                    extensions={
                        "timeout": {
                            "connect": timeout,
                            "read": timeout,
                            "write": timeout,
                            "pool": timeout,
                        }
                    },
                ) as response:
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_stream():
                        size += len(chunk)
                        if size > MAX_RUBRIC_RESPONSE_BYTES:
                            raise RubricGenerationError(
                                "rubric_provider_response_too_large",
                                "供应商生成响应超过安全上限",
                            )
                        chunks.append(chunk)
                    try:
                        payload = json.loads(b"".join(chunks))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        payload = {}
                    return ProviderHttpResponse(
                        status_code=response.status,
                        json_body=payload,
                    )
            except TimeoutException as error:
                raise RubricGenerationError(
                    "rubric_provider_timeout",
                    "供应商生成评分标准超时",
                ) from error
            except (NetworkError, ProtocolError) as error:
                raise RubricGenerationError(
                    "rubric_provider_unavailable",
                    "无法安全连接供应商生成服务",
                ) from error
        finally:
            await pool.aclose()


class OpenAICompatibleRubricGenerator:
    """调用一次 chat completions，并拒绝修补任何不合规响应。"""

    def __init__(
        self,
        *,
        url_policy: ProviderBaseUrlPolicy,
        http_client: RubricHttpClient,
    ) -> None:
        self._url_policy = url_policy
        self._http_client = http_client

    @staticmethod
    def _messages(request: RubricGenerationRequest) -> list[dict[str, str]]:
        minimal_example = {
            "schema_version": 1,
            "total_score": "1",
            "score_step": "1",
            "dimensions": [
                {
                    "id": "criterion",
                    "name": "Criterion",
                    "description": "What is assessed.",
                    "max_score": "1",
                    "bands": [
                        {
                            "label": "Not met",
                            "min_score": "0",
                            "max_score": "0",
                            "description": "The criterion is not met.",
                        },
                        {
                            "label": "Met",
                            "min_score": "1",
                            "max_score": "1",
                            "description": "The criterion is met.",
                        },
                    ],
                    "evidence_requirements": ["Quote supporting evidence."],
                }
            ],
            "deductions": [],
        }
        system_prompt = (
            "You convert a teacher rubric into one JSON object. Return JSON only. "
            "The object must use schema_version 1 and contain total_score, score_step, "
            "dimensions, and deductions. Dimension ids must be lowercase snake_case and "
            "unique. Dimension names must be unique. Dimension scores must add to the exact "
            "total. Every score must match the exact score step. Each dimension must have "
            "ordered bands that continuously cover 0 through its max score, inclusive, and "
            "must include non-empty evidence requirements. Do not invent a different total "
            "or score step. Every decimal score must be a JSON string. A minimal valid "
            "shape is: " + json.dumps(minimal_example, ensure_ascii=False, separators=(",", ":"))
        )
        user_payload = {
            "assignment_title": request.assignment_title,
            "assignment_instructions": request.assignment_instructions,
            "original_rubric": request.original_rubric,
            "required_total_score": str(request.total_score),
            "required_score_step": str(request.score_step),
        }
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Create the JSON rubric from this input:\n"
                + json.dumps(user_payload, ensure_ascii=False),
            },
        ]

    @staticmethod
    def _validate_usage(payload: dict[str, object]) -> None:
        usage = payload.get("usage")
        if usage is None:
            return
        if not isinstance(usage, dict):
            raise RubricGenerationError(
                "rubric_provider_response_invalid",
                "模型返回了无效的用量信息",
            )
        core_values: dict[str, int] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if type(value) is not int or value < 0:
                raise RubricGenerationError(
                    "rubric_provider_response_invalid",
                    "模型返回了无效的用量信息",
                )
            core_values[key] = value
        if core_values["total_tokens"] != (
            core_values["prompt_tokens"] + core_values["completion_tokens"]
        ):
            raise RubricGenerationError(
                "rubric_provider_response_invalid",
                "模型返回了不一致的用量信息",
            )
        cache_keys = ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens")
        if any(key in usage for key in cache_keys):
            cache_values: list[int] = []
            for key in cache_keys:
                value = usage.get(key)
                if type(value) is not int or value < 0:
                    raise RubricGenerationError(
                        "rubric_provider_response_invalid",
                        "模型返回了无效的缓存用量信息",
                    )
                cache_values.append(value)
            if sum(cache_values) != core_values["prompt_tokens"]:
                raise RubricGenerationError(
                    "rubric_provider_response_invalid",
                    "模型返回了不一致的缓存用量信息",
                )

    @staticmethod
    def _extract_structured_rubric(
        payload: object,
        request: RubricGenerationRequest,
    ) -> StructuredRubric:
        try:
            if (
                not isinstance(payload, dict)
                or payload.get("object") != "chat.completion"
                or payload.get("model") != request.model
                or not isinstance(payload.get("id"), str)
                or not payload["id"]
                or type(payload.get("created")) is not int
                or payload["created"] < 0
            ):
                raise TypeError
            OpenAICompatibleRubricGenerator._validate_usage(payload)
            choices = payload["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise TypeError
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("index") != 0:
                raise TypeError
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length":
                raise RubricGenerationError(
                    "rubric_provider_output_truncated",
                    "模型输出达到长度上限，结构化评分标准不完整",
                )
            if finish_reason == "content_filter":
                raise RubricGenerationError(
                    "rubric_provider_content_filtered",
                    "供应商拒绝生成该评分标准",
                )
            if finish_reason != "stop":
                raise TypeError
            message = choice["message"]
            if (
                not isinstance(message, dict)
                or message.get("role") != "assistant"
                or message.get("reasoning_content") not in {None, ""}
            ):
                raise TypeError
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise TypeError
            decoded = json.loads(content, parse_float=Decimal)
            rubric = StructuredRubric.model_validate(decoded)
        except RubricGenerationError:
            raise
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError) as error:
            raise RubricGenerationError(
                "rubric_provider_response_invalid",
                "模型没有返回有效的结构化评分标准",
            ) from error
        if rubric.total_score != request.total_score or rubric.score_step != request.score_step:
            raise RubricGenerationError(
                "rubric_provider_response_invalid",
                "模型返回的总分或评分步长不一致",
            )
        return rubric

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        if status_code in {401, 403}:
            raise RubricGenerationError(
                "rubric_provider_authentication_failed",
                "供应商凭证无效或无权生成评分标准",
            )
        if status_code == 402:
            raise RubricGenerationError(
                "rubric_provider_balance_unavailable",
                "供应商账户余额不足",
            )
        if status_code in {400, 422}:
            raise RubricGenerationError(
                "rubric_provider_request_invalid",
                "供应商不接受当前结构化生成请求",
            )
        if status_code == 429:
            raise RubricGenerationError(
                "rubric_provider_rate_limited",
                "供应商暂时限制生成请求",
            )
        if 300 <= status_code < 400:
            raise RubricGenerationError(
                "rubric_provider_redirect_rejected",
                "供应商生成接口不允许重定向",
            )
        if status_code >= 500:
            raise RubricGenerationError(
                "rubric_provider_unavailable",
                "供应商生成服务暂时不可用",
            )
        if status_code != 200:
            raise RubricGenerationError(
                "rubric_provider_request_rejected",
                "供应商拒绝了生成请求",
            )

    async def generate(self, request: RubricGenerationRequest) -> StructuredRubric:
        if request.provider_type not in OPENAI_COMPATIBLE_PROVIDER_TYPES:
            raise RubricGenerationError(
                "rubric_provider_unsupported",
                "当前供应商尚不支持结构化 Rubric 生成",
            )
        body: dict[str, object] = {
            "model": request.model,
            "messages": self._messages(request),
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": MAX_RUBRIC_OUTPUT_TOKENS,
            "stream": False,
        }
        if request.provider_type is ProviderType.DEEPSEEK:
            body["thinking"] = {"type": "disabled"}
        try:
            async with asyncio.timeout(float(request.timeout_seconds)):
                target = await self._url_policy.validate(
                    request.provider_type,
                    request.base_url,
                )
                response = await self._http_client.post_json(
                    target=target,
                    url=f"{target.value}/chat/completions",
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": (f"Bearer {request.api_key.get_secret_value()}"),
                    },
                    json_body=body,
                    timeout_seconds=request.timeout_seconds,
                )
        except TimeoutError as error:
            raise RubricGenerationError(
                "rubric_provider_timeout",
                "供应商生成评分标准超时",
            ) from error
        self._raise_for_status(response.status_code)
        return self._extract_structured_rubric(response.json_body, request)
