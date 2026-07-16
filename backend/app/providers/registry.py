"""供应商适配器的精确注册表。"""

from collections.abc import Mapping

from app.domain.enums import ProviderType
from app.providers.anthropic import AnthropicAdapter
from app.providers.base import ProviderAdapter, ProviderAdapterError, ProviderAdapterHttpClient
from app.providers.connection import ProviderBaseUrlPolicy
from app.providers.deepseek import DeepSeekAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.glm import GlmAdapter
from app.providers.kimi import KimiAdapter
from app.providers.openai import OpenAIAdapter
from app.providers.openai_compatible import OpenAICompatibleAdapter


class ProviderAdapterRegistry:
    """只返回明确选择的适配器；失败时绝不遍历其他供应商。"""

    def __init__(self, adapters: Mapping[ProviderType, ProviderAdapter]) -> None:
        self._adapters = dict(adapters)

    def require(self, provider_type: ProviderType) -> ProviderAdapter:
        adapter = self._adapters.get(provider_type)
        if adapter is None:
            raise ProviderAdapterError(
                "provider_adapter_unavailable",
                "当前供应商没有可用评分适配器",
            )
        return adapter


def build_provider_adapter_registry(
    *,
    url_policy: ProviderBaseUrlPolicy,
    http_client: ProviderAdapterHttpClient,
) -> ProviderAdapterRegistry:
    """构造七类供应商的一对一注册表。"""

    return ProviderAdapterRegistry(
        {
            ProviderType.DEEPSEEK: DeepSeekAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
            ProviderType.KIMI: KimiAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
            ProviderType.GLM: GlmAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
            ProviderType.OPENAI: OpenAIAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
            ProviderType.ANTHROPIC: AnthropicAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
            ProviderType.GEMINI: GeminiAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
            ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleAdapter(
                url_policy=url_policy,
                http_client=http_client,
            ),
        }
    )
