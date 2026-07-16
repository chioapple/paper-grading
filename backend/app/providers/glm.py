"""智谱 GLM 评分适配器。"""

from app.domain.enums import ProviderType
from app.providers.base import (
    ProviderAdapterError,
    ProviderGradeRequest,
    ProviderHttpResponse,
)
from app.providers.openai_compatible import OpenAICompatibleAdapter


class GlmAdapter(OpenAICompatibleAdapter):
    """GLM 通过 do_sample=false 固定采样，不假定存在 Models API。"""

    provider_type = ProviderType.GLM

    def _raise_for_status(self, response: ProviderHttpResponse) -> None:
        payload = response.json_body
        error_payload = payload.get("error") if isinstance(payload, dict) else None
        error_code = error_payload.get("code") if isinstance(error_payload, dict) else None
        normalized_code = str(error_code) if error_code is not None else ""
        if normalized_code in {"1000", "1001", "1003"}:
            raise ProviderAdapterError(
                "provider_authentication_failed",
                "GLM 凭证无效或无权调用模型",
                response=response,
            )
        if normalized_code in {"1113", "1308"}:
            raise ProviderAdapterError(
                "provider_quota_exhausted",
                "GLM 账户当前额度已用尽",
                response=response,
            )
        if normalized_code == "1301":
            raise ProviderAdapterError(
                "provider_content_refused",
                "GLM 拒绝了该评分内容",
                response=response,
            )
        if normalized_code in {"1200", "1230", "1234", "1305"}:
            raise ProviderAdapterError(
                "provider_unavailable",
                "GLM 模型服务暂时不可用",
                retryable=True,
                response=response,
            )
        super()._raise_for_status(response)

    def _validate_capabilities(self, request: ProviderGradeRequest) -> None:
        super()._validate_capabilities(request)
        capabilities = request.capabilities
        if (
            capabilities.structured_output != "json_object"
            or capabilities.schema_dialect != "canonical"
            or capabilities.sampling_policy != "do_sample_false"
            or capabilities.thinking_policy != "disabled"
            or capabilities.output_token_parameter != "max_tokens"
            or capabilities.supports_model_listing
        ):
            raise ProviderAdapterError(
                "provider_capability_unsupported",
                "GLM 模型能力快照不受当前适配器支持",
            )
