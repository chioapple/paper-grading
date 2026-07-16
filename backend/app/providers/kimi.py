"""Moonshot Kimi 评分适配器。"""

from app.domain.enums import ProviderType
from app.providers.base import (
    ProviderAdapterError,
    ProviderGradeRequest,
    ProviderHttpResponse,
)
from app.providers.openai_compatible import OpenAICompatibleAdapter


class KimiAdapter(OpenAICompatibleAdapter):
    """Kimi 使用显式模型能力，禁止套用通用 temperature=0。"""

    provider_type = ProviderType.KIMI

    def _raise_for_status(self, response: ProviderHttpResponse) -> None:
        payload = response.json_body
        error_payload = payload.get("error") if isinstance(payload, dict) else None
        error_code = error_payload.get("code") if isinstance(error_payload, dict) else None
        if error_code == "exceeded_current_quota_error":
            raise ProviderAdapterError(
                "provider_quota_exhausted",
                "Kimi 账户当前额度已用尽",
                response=response,
            )
        if error_code == "engine_overloaded_error":
            raise ProviderAdapterError(
                "provider_unavailable",
                "Kimi 模型服务暂时过载",
                retryable=True,
                response=response,
            )
        if error_code == "content_filter":
            raise ProviderAdapterError(
                "provider_content_refused",
                "Kimi 拒绝了该评分内容",
                response=response,
            )
        super()._raise_for_status(response)

    def _validate_capabilities(self, request: ProviderGradeRequest) -> None:
        super()._validate_capabilities(request)
        capabilities = request.capabilities
        if (
            capabilities.structured_output != "json_object"
            or capabilities.schema_dialect != "canonical"
            or capabilities.sampling_policy not in {"omit", "temperature_fixed_0_6"}
            or capabilities.thinking_policy not in {"disabled", "omit"}
            or capabilities.output_token_parameter != "max_completion_tokens"
        ):
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "Kimi 模型能力快照不受当前适配器支持",
            )
