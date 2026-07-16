"""供应商适配器注册表不得自动换模型或换供应商。"""

import pytest

from app.domain.enums import ProviderType
from app.providers.base import (
    ProviderAdapterError,
    ProviderCredentialValidation,
    ProviderGradeRequest,
    ProviderGradeResult,
)
from app.providers.registry import ProviderAdapterRegistry


class SelectedAdapter:
    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
        raise ProviderAdapterError("provider_unavailable", "selected provider failed")

    async def validate_credentials(
        self,
        request: ProviderGradeRequest,
    ) -> ProviderCredentialValidation:
        raise AssertionError("not used")


class UnexpectedFallbackAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
        self.calls += 1
        raise AssertionError("fallback must not run")

    async def validate_credentials(
        self,
        request: ProviderGradeRequest,
    ) -> ProviderCredentialValidation:
        raise AssertionError("not used")


@pytest.mark.anyio
async def test_registry_never_falls_back_after_the_selected_adapter_fails() -> None:
    selected = SelectedAdapter()
    unexpected = UnexpectedFallbackAdapter()
    registry = ProviderAdapterRegistry(
        {
            ProviderType.DEEPSEEK: selected,
            ProviderType.OPENAI: unexpected,
        }
    )

    with pytest.raises(ProviderAdapterError, match="selected provider failed"):
        await registry.require(ProviderType.DEEPSEEK).grade(object())  # type: ignore[arg-type]

    assert unexpected.calls == 0
