"""阶段九模型适配器共享的不可变公共契约。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.domain.enums import ProviderType
from app.domain.grading import canonical_json_bytes, canonical_sha256
from app.grading.prompt import GradingPrompt
from app.providers.connection import ProviderBaseUrlPolicy, ValidatedBaseUrl

StructuredOutputMode = Literal["json_schema", "json_object"]
SchemaDialect = Literal["canonical", "openai", "anthropic", "gemini"]
SamplingPolicy = Literal["temperature_zero", "temperature_fixed_0_6", "do_sample_false", "omit"]
ThinkingPolicy = Literal["disabled", "enabled", "omit"]
RetrySafety = Literal["never", "safe", "unknown"]
OutputTokenParameter = Literal[
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
]


class ProviderAdapterError(RuntimeError):
    """供应商调用失败；只暴露稳定错误码和安全说明。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_safety: RetrySafety | None = None,
        response: ProviderHttpResponse | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_safety = retry_safety or ("unknown" if retryable else "never")
        if self.retry_safety == "safe" and not self.retryable:
            raise ValueError("只有可重试错误才能标记为安全重试")
        self.response = response


class ProviderTokenPriceTier(BaseModel):
    """按总输入 Token 选择的单档价格；末档必须无上限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    up_to_input_tokens: int | None = Field(default=None, gt=0)
    input_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=9)
    cache_read_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=9)
    cache_write_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=9)
    output_per_million: Decimal = Field(ge=0, max_digits=18, decimal_places=9)


class ProviderPricing(BaseModel):
    """显式、可审计、可更新的价格快照；适配器不硬编码价格。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tariff_version: str = Field(min_length=1, max_length=100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    tiers: tuple[ProviderTokenPriceTier, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_tiers(self) -> ProviderPricing:
        finite_limits = [
            tier.up_to_input_tokens for tier in self.tiers if tier.up_to_input_tokens is not None
        ]
        if self.tiers[-1].up_to_input_tokens is not None:
            raise ValueError("价格快照最后一档必须覆盖全部剩余输入长度")
        if any(tier.up_to_input_tokens is None for tier in self.tiers[:-1]):
            raise ValueError("只有价格快照最后一档可以没有输入上限")
        if finite_limits != sorted(set(finite_limits)):
            raise ValueError("价格分档上限必须严格递增且不得重复")
        return self


class ProviderModelCapabilities(BaseModel):
    """由管理员确认并随批次锁定的精确模型能力快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_version: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=255)
    context_window_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    structured_output: StructuredOutputMode
    schema_dialect: SchemaDialect
    sampling_policy: SamplingPolicy
    thinking_policy: ThinkingPolicy
    output_token_parameter: OutputTokenParameter
    supports_model_listing: bool
    pricing: ProviderPricing | None = None


class ProviderModelProfile(BaseModel):
    """管理员确认的模型能力和一次评分的保守输出上限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capabilities: ProviderModelCapabilities
    grading_max_output_tokens: int = Field(gt=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_output_limit(self) -> ProviderModelProfile:
        if self.grading_max_output_tokens > self.capabilities.max_output_tokens:
            raise ValueError("评分输出上限超过模型能力快照")
        return self


class ProviderGradeRequest(BaseModel):
    """一次模型评分调用所需的不可变配置、能力、Schema 和提示快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_config_id: UUID
    config_version: int = Field(gt=0)
    provider_type: ProviderType
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr = Field(repr=False, min_length=1, max_length=4096)
    model: str = Field(min_length=1, max_length=255)
    timeout_seconds: Decimal = Field(gt=0, le=300, max_digits=8, decimal_places=3)
    max_output_tokens: int = Field(gt=0, le=1_000_000)
    capabilities: ProviderModelCapabilities
    result_schema_json: bytes = Field(min_length=2, max_length=1_000_000, repr=False)
    prompt: GradingPrompt

    @model_validator(mode="after")
    def validate_snapshot(self) -> ProviderGradeRequest:
        if self.capabilities.model != self.model:
            raise ValueError("模型能力快照与请求模型不一致")
        if self.max_output_tokens > self.capabilities.max_output_tokens:
            raise ValueError("请求输出上限超过模型能力快照")
        if hashlib.sha256(self.result_schema_json).digest() != self.prompt.result_schema_hash:
            raise ValueError("结果 Schema 正文与阶段八哈希不一致")
        try:
            decoded_schema = json.loads(self.result_schema_json)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("结果 Schema 正文不是有效 JSON") from error
        if not isinstance(decoded_schema, dict):
            raise ValueError("结果 Schema 根节点必须是对象")
        if canonical_json_bytes(decoded_schema) != self.result_schema_json:
            raise ValueError("结果 Schema 正文不是规范 JSON")
        return self

    def snapshot_hash(self) -> bytes:
        """覆盖所有不能在同一批次或唯一纠正调用中变化的字段。"""

        return canonical_sha256(
            {
                "provider_config_id": self.provider_config_id,
                "config_version": self.config_version,
                "provider_type": self.provider_type.value,
                "base_url": self.base_url,
                "model": self.model,
                "timeout_seconds": self.timeout_seconds,
                "max_output_tokens": self.max_output_tokens,
                "capabilities": self.capabilities,
                "prompt_version": self.prompt.prompt_version,
                "prompt_hash": self.prompt.prompt_hash.hex(),
                "result_schema_hash": self.prompt.result_schema_hash.hex(),
                "rubric_hash": self.prompt.rubric_hash.hex(),
                "base_request_hash": self.prompt.base_request_hash.hex(),
            }
        )


class ProviderHttpResponse(BaseModel):
    """外部 HTTP 边界返回的完整原始响应和已解析 JSON。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int
    json_body: object
    raw_body: bytes = Field(max_length=1_000_000)
    headers: dict[str, str] = Field(default_factory=dict)


def raise_for_provider_status(
    response: ProviderHttpResponse,
    *,
    provider_type: ProviderType,
) -> None:
    """把共有 HTTP 状态转换为稳定错误码，不透传上游正文。"""

    status_code = response.status_code
    if status_code == 200:
        return
    if 300 <= status_code < 400:
        raise ProviderAdapterError(
            "provider_redirect_rejected",
            "供应商评分接口不允许重定向",
            response=response,
        )
    if status_code == 401 or status_code == 403 and provider_type is ProviderType.GEMINI:
        raise ProviderAdapterError(
            "provider_authentication_failed",
            "供应商凭证无效或无权调用模型",
            response=response,
        )
    if status_code == 403:
        raise ProviderAdapterError(
            "provider_permission_denied",
            "供应商拒绝当前凭证访问模型",
            response=response,
        )
    if status_code == 402:
        raise ProviderAdapterError(
            "provider_balance_unavailable",
            "供应商账户余额不足",
            response=response,
        )
    if status_code in {400, 422}:
        raise ProviderAdapterError(
            "provider_request_invalid",
            "供应商不接受当前评分请求",
            response=response,
        )
    if status_code == 404:
        raise ProviderAdapterError(
            "provider_endpoint_invalid",
            "供应商评分接口不存在",
            response=response,
        )
    if status_code in {408, 504}:
        raise ProviderAdapterError(
            "provider_timeout",
            "供应商评分请求超时",
            retryable=True,
            retry_safety="safe",
            response=response,
        )
    if status_code == 429:
        raise ProviderAdapterError(
            "provider_rate_limited",
            "供应商暂时限制评分请求",
            retryable=True,
            retry_safety="safe",
            response=response,
        )
    if status_code in {500, 502, 503, 529}:
        raise ProviderAdapterError(
            "provider_unavailable",
            "供应商评分服务暂时不可用",
            retryable=True,
            retry_safety="safe",
            response=response,
        )
    raise ProviderAdapterError(
        "provider_request_failed",
        "供应商拒绝了评分请求",
        response=response,
    )


class ProviderTokenUsage(BaseModel):
    """供应商无关的 Token 用量；缓存和推理 Token 均是总量子集。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    cache_write_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_subsets(self) -> ProviderTokenUsage:
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ValueError("缓存输入 Token 不能超过总输入 Token")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("推理 Token 不能超过总输出 Token")
        return self


class ProviderCostEstimate(BaseModel):
    """按价格快照和真实用量计算出的精确估算。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tariff_version: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: Decimal = Field(ge=0)
    estimated: Literal[True] = True


class ProviderGradeResult(BaseModel):
    """所有供应商评分调用统一返回的可审计结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_type: ProviderType
    requested_model: str = Field(min_length=1, max_length=255)
    reported_model: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=500)
    finish_reason: Literal["completed"] = "completed"
    output_text: str = Field(min_length=1, max_length=1_000_000)
    usage: ProviderTokenUsage
    estimated_cost: ProviderCostEstimate | None
    raw_response: bytes = Field(max_length=1_000_000, repr=False)
    raw_response_sha256: bytes = Field(min_length=32, max_length=32)
    sent_schema_sha256: bytes = Field(min_length=32, max_length=32)


class ProviderCredentialValidation(BaseModel):
    """通过模型列表或真实冒烟确认的凭证与模型结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_type: ProviderType
    model: str
    method: Literal["models", "smoke"]
    request_id: str | None
    available_models: tuple[str, ...] = Field(default_factory=tuple, max_length=10_000)
    billable: bool


class ProviderAdapterBase:
    """所有供应商共享且不依赖协议的确定性行为。"""

    provider_type: ProviderType
    _url_policy: ProviderBaseUrlPolicy
    _http_client: ProviderAdapterHttpClient

    @staticmethod
    def estimate_cost(
        *,
        usage: ProviderTokenUsage,
        pricing: ProviderPricing | None,
    ) -> ProviderCostEstimate | None:
        if pricing is None:
            return None
        tier = next(
            (
                candidate
                for candidate in pricing.tiers
                if candidate.up_to_input_tokens is None
                or usage.input_tokens <= candidate.up_to_input_tokens
            ),
            None,
        )
        if tier is None:
            raise ValueError("价格快照没有覆盖当前输入长度")
        uncached_input_tokens = (
            usage.input_tokens - usage.cached_input_tokens - usage.cache_write_input_tokens
        )
        amount = (
            Decimal(uncached_input_tokens) * tier.input_per_million
            + Decimal(usage.cached_input_tokens) * tier.cache_read_per_million
            + Decimal(usage.cache_write_input_tokens) * tier.cache_write_per_million
            + Decimal(usage.output_tokens) * tier.output_per_million
        ) / Decimal(1_000_000)
        return ProviderCostEstimate(
            tariff_version=pricing.tariff_version,
            currency=pricing.currency,
            amount=amount,
        )

    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
        raise NotImplementedError

    async def validate_credentials(
        self,
        request: ProviderGradeRequest,
    ) -> ProviderCredentialValidation:
        """能力允许时走 Models API；否则执行明确标记为可计费的真实冒烟。"""

        if request.provider_type is not self.provider_type:
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "适配器与供应商类型不一致",
            )
        if request.capabilities.supports_model_listing:
            try:
                async with asyncio.timeout(float(request.timeout_seconds)):
                    target = await self._url_policy.validate(
                        self.provider_type,
                        request.base_url,
                    )
                    url, headers = self._model_list_request_parts(request, target)
                    response = await self._http_client.get_json(
                        target=target,
                        url=url,
                        headers=headers,
                        timeout_seconds=request.timeout_seconds,
                    )
            except TimeoutError as error:
                raise ProviderAdapterError(
                    "provider_timeout",
                    "供应商模型列表请求超时",
                    retryable=True,
                ) from error
            raise_for_provider_status(response, provider_type=self.provider_type)
            models = self._extract_model_ids(response.json_body)
            if request.model not in models:
                raise ProviderAdapterError(
                    "provider_model_unavailable",
                    "已配置模型不在供应商模型列表中",
                    response=response,
                )
            request_id = next(
                (
                    response.headers[name]
                    for name in ("x-request-id", "openai-request-id", "request-id")
                    if name in response.headers
                ),
                None,
            )
            return ProviderCredentialValidation(
                provider_type=self.provider_type,
                model=request.model,
                method="models",
                request_id=request_id,
                available_models=tuple(models),
                billable=False,
            )
        result = await self.grade(request)
        return ProviderCredentialValidation(
            provider_type=result.provider_type,
            model=result.requested_model,
            method="smoke",
            request_id=result.request_id,
            billable=True,
        )

    def _model_list_request_parts(
        self,
        request: ProviderGradeRequest,
        target: ValidatedBaseUrl,
    ) -> tuple[str, dict[str, str]]:
        headers = {"Accept": "application/json"}
        api_key = request.api_key.get_secret_value()
        if self.provider_type is ProviderType.ANTHROPIC:
            headers["anthropic-version"] = "2023-06-01"
            headers["x-api-key"] = api_key
            return f"{target.value}/v1/models?limit=1000", headers
        if self.provider_type is ProviderType.GEMINI:
            headers["x-goog-api-key"] = api_key
            return f"{target.value}/v1beta/models?pageSize=1000", headers
        headers["Authorization"] = f"Bearer {api_key}"
        return f"{target.value}/models", headers

    def _extract_model_ids(self, payload: object) -> list[str]:
        if not isinstance(payload, dict):
            raise ProviderAdapterError(
                "provider_response_invalid",
                "供应商返回了无效模型列表",
            )
        list_key = "models" if self.provider_type is ProviderType.GEMINI else "data"
        raw_models = payload.get(list_key)
        if not isinstance(raw_models, list):
            raise ProviderAdapterError(
                "provider_response_invalid",
                "供应商返回了无效模型列表",
            )
        id_key = "name" if self.provider_type is ProviderType.GEMINI else "id"
        models = [
            value.removeprefix("models/")
            for item in raw_models
            if isinstance(item, dict) and isinstance((value := item.get(id_key)), str) and value
        ]
        if not models:
            raise ProviderAdapterError(
                "provider_response_invalid",
                "供应商没有返回可用模型",
            )
        return models


class ProviderAdapterHttpClient(Protocol):
    """模型适配器唯一可替换的外部网络边界。"""

    async def post_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse: ...

    async def get_json(
        self,
        *,
        target: ValidatedBaseUrl,
        url: str,
        headers: dict[str, str],
        timeout_seconds: Decimal,
    ) -> ProviderHttpResponse: ...


class ProviderAdapter(Protocol):
    """阶段十批量任务只依赖这个统一评分入口。"""

    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult: ...

    async def validate_credentials(
        self,
        request: ProviderGradeRequest,
    ) -> ProviderCredentialValidation: ...
