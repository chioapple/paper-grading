"""供应商配置业务契约测试。"""

import base64
from datetime import datetime
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from app.providers.config import (
    ProviderConfigCreate,
    ProviderConfigService,
    ProviderConfigUpdate,
    ProviderConfigUpdateValues,
    ProviderConfigurationError,
    ProviderStateError,
    StoredProviderConfig,
)
from app.providers.connection import (
    ProviderBaseUrlPolicy,
    ProviderConnectionRequest,
    ProviderConnectionResult,
    ProviderUrlError,
)
from app.security.encryption import ApiKeyCipher


class InMemoryProviderRepository:
    """数据库边界的最小内存实现。"""

    def __init__(self) -> None:
        self.saved: StoredProviderConfig | None = None

    async def create(self, config: StoredProviderConfig) -> StoredProviderConfig:
        self.saved = config
        return config

    async def list_all(self) -> list[StoredProviderConfig]:
        return [self.saved] if self.saved is not None else []

    async def get(self, provider_id: UUID) -> StoredProviderConfig | None:
        if self.saved is None or self.saved.id != provider_id:
            return None
        return self.saved

    async def mark_tested(
        self,
        provider_id: UUID,
        *,
        expected_config_version: int,
        tested_at: datetime,
    ) -> StoredProviderConfig | None:
        if (
            self.saved is None
            or self.saved.id != provider_id
            or self.saved.config_version != expected_config_version
        ):
            return None
        self.saved = self.saved.model_copy(
            update={
                "tested_at": tested_at,
                "tested_config_version": expected_config_version,
                "updated_at": tested_at,
            }
        )
        return self.saved

    async def enable_tested(self, provider_id: UUID) -> StoredProviderConfig | None:
        if (
            self.saved is None
            or self.saved.id != provider_id
            or self.saved.tested_config_version != self.saved.config_version
        ):
            return None
        self.saved = self.saved.model_copy(update={"status": "enabled"})
        return self.saved

    async def update(
        self,
        provider_id: UUID,
        *,
        expected_config_version: int,
        values: ProviderConfigUpdateValues,
    ) -> StoredProviderConfig | None:
        if (
            self.saved is None
            or self.saved.id != provider_id
            or self.saved.config_version != expected_config_version
        ):
            return None
        changes = values.model_dump()
        sensitive_fields = {
            "provider_type",
            "base_url",
            "encrypted_api_key",
            "api_key_nonce",
            "allowed_models",
            "default_model",
            "timeout_seconds",
        }
        sensitive_changed = any(
            getattr(self.saved, field) != changes[field] for field in sensitive_fields
        )
        if sensitive_changed:
            changes.update(
                {
                    "config_version": self.saved.config_version + 1,
                    "tested_config_version": None,
                    "tested_at": None,
                    "status": "draft",
                }
            )
        self.saved = self.saved.model_copy(update=changes)
        return self.saved

    async def list_enabled(self) -> list[StoredProviderConfig]:
        if self.saved is None or self.saved.status != "enabled":
            return []
        return [self.saved]

    async def disable_enabled(self, provider_id: UUID) -> StoredProviderConfig | None:
        if self.saved is None or self.saved.id != provider_id or self.saved.status != "enabled":
            return None
        self.saved = self.saved.model_copy(update={"status": "disabled"})
        return self.saved


@pytest.mark.parametrize("invalid_key", ["包含中文", "line\nbreak", "space key"])
def test_api_key_must_be_a_printable_ascii_header_value(invalid_key: str) -> None:
    with pytest.raises(ValidationError, match="可打印 ASCII"):
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr(invalid_key),
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget=None,
        )


@pytest.mark.anyio
async def test_admin_can_create_a_deepseek_config_without_exposing_the_key() -> None:
    repository = InMemoryProviderRepository()
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode("ascii"))
    service = ProviderConfigService(repository=repository, cipher=cipher)

    view = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash", "deepseek-v4-pro"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget="20.00",
        )
    )

    payload = view.model_dump()
    assert payload["api_key_configured"] is True
    assert payload["configuration_tested"] is False
    assert payload["can_enable"] is False
    assert "api_key" not in payload
    assert "encrypted_api_key" not in payload
    assert "api_key_nonce" not in payload
    assert repository.saved is not None
    assert repository.saved.encrypted_api_key is not None
    assert b"stage-five-canary-key" not in repository.saved.encrypted_api_key


@pytest.mark.anyio
async def test_successful_connection_test_allows_enabling_the_same_config_version() -> None:
    repository = InMemoryProviderRepository()
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode("ascii"))

    class SuccessfulTester:
        async def test(self, request: ProviderConnectionRequest) -> ProviderConnectionResult:
            assert request.api_key == "stage-five-canary-key"
            return ProviderConnectionResult(
                available_models=["deepseek-v4-flash", "deepseek-v4-pro"]
            )

    service = ProviderConfigService(
        repository=repository,
        cipher=cipher,
        connection_tester=SuccessfulTester(),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash", "deepseek-v4-pro"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget="20.00",
        )
    )

    tested = await service.test_connection(created.id)
    enabled = await service.enable(created.id)

    assert tested.provider.configuration_tested is True
    assert tested.provider.can_enable is True
    assert tested.available_models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert enabled.status == "enabled"


@pytest.mark.anyio
async def test_changing_the_default_model_invalidates_the_previous_connection_test() -> None:
    repository = InMemoryProviderRepository()
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode("ascii"))

    class SuccessfulTester:
        async def test(self, request: object) -> ProviderConnectionResult:
            return ProviderConnectionResult(
                available_models=["deepseek-v4-flash", "deepseek-v4-pro"]
            )

    service = ProviderConfigService(
        repository=repository,
        cipher=cipher,
        connection_tester=SuccessfulTester(),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash", "deepseek-v4-pro"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget="20.00",
        )
    )
    await service.test_connection(created.id)

    updated = await service.update(
        created.id,
        ProviderConfigUpdate(default_model="deepseek-v4-pro"),
    )

    assert updated.configuration_tested is False
    assert updated.can_enable is False
    with pytest.raises(ProviderStateError, match="测试通过"):
        await service.enable(created.id)


@pytest.mark.anyio
async def test_updating_a_legacy_draft_without_a_default_model_is_rejected_cleanly() -> None:
    repository = InMemoryProviderRepository()
    service = ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(
            base64.b64encode(bytes(range(32))).decode("ascii")
        ),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget=None,
        )
    )
    assert repository.saved is not None
    repository.saved = repository.saved.model_copy(update={"default_model": None})

    with pytest.raises(ProviderConfigurationError, match="默认模型尚未配置"):
        await service.update(created.id, ProviderConfigUpdate(name="DeepSeek 草稿"))


@pytest.mark.anyio
async def test_updating_a_legacy_draft_can_supply_its_missing_api_key() -> None:
    repository = InMemoryProviderRepository()

    class ReplacementKeyTester:
        async def test(self, request: ProviderConnectionRequest) -> ProviderConnectionResult:
            assert request.api_key == "replacement-canary-key"
            return ProviderConnectionResult(available_models=["deepseek-v4-flash"])

    service = ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(
            base64.b64encode(bytes(range(32))).decode("ascii")
        ),
        connection_tester=ReplacementKeyTester(),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget=None,
        )
    )
    assert repository.saved is not None
    repository.saved = repository.saved.model_copy(
        update={"encrypted_api_key": None, "api_key_nonce": None}
    )

    updated = await service.update(
        created.id,
        ProviderConfigUpdate(api_key=SecretStr("replacement-canary-key")),
    )
    tested = await service.test_connection(created.id)

    assert updated.api_key_configured is True
    assert tested.provider.configuration_tested is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        ProviderConfigUpdate(default_model="deepseek-v4-pro"),
        ProviderConfigUpdate(allowed_models=["deepseek-v4-pro"]),
    ],
)
async def test_update_rejects_a_default_model_outside_the_allowed_models(
    payload: ProviderConfigUpdate,
) -> None:
    repository = InMemoryProviderRepository()
    service = ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(
            base64.b64encode(bytes(range(32))).decode("ascii")
        ),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget=None,
        )
    )

    with pytest.raises(ProviderConfigurationError, match="默认模型必须包含在允许模型中"):
        await service.update(created.id, payload)


@pytest.mark.anyio
async def test_custom_provider_with_a_private_base_url_is_not_saved() -> None:
    repository = InMemoryProviderRepository()

    class PrivateResolver:
        async def resolve(self, host: str, port: int) -> tuple[str, ...]:
            return ("10.0.0.8",)

    service = ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(
            base64.b64encode(bytes(range(32))).decode("ascii")
        ),
        url_policy=ProviderBaseUrlPolicy(resolver=PrivateResolver()),
    )

    with pytest.raises(ProviderUrlError, match="公网"):
        await service.create(
            ProviderConfigCreate(
                provider_type="openai_compatible",
                name="自定义模型",
                base_url="https://models.example.com/v1",
                api_key=SecretStr("stage-five-canary-key"),
                allowed_models=["grading-model"],
                default_model="grading-model",
                timeout_seconds="60",
                max_concurrency=1,
                monthly_budget=None,
            )
        )

    assert repository.saved is None


@pytest.mark.anyio
async def test_teacher_model_catalog_only_contains_enabled_allowed_models() -> None:
    repository = InMemoryProviderRepository()

    class SuccessfulTester:
        async def test(self, request: object) -> ProviderConnectionResult:
            return ProviderConnectionResult(
                available_models=["deepseek-v4-flash", "deepseek-v4-pro"]
            )

    service = ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(
            base64.b64encode(bytes(range(32))).decode("ascii")
        ),
        connection_tester=SuccessfulTester(),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget="20.00",
        )
    )

    assert await service.list_teacher_models() == []

    await service.test_connection(created.id)
    await service.enable(created.id)

    catalog = await service.list_teacher_models()
    assert [item.model_dump() for item in catalog] == [
        {
            "provider_id": created.id,
            "provider_name": "DeepSeek 主账号",
            "provider_type": "deepseek",
            "allowed_models": ["deepseek-v4-flash"],
            "default_model": "deepseek-v4-flash",
        }
    ]


@pytest.mark.anyio
async def test_enabled_provider_can_be_disabled() -> None:
    repository = InMemoryProviderRepository()

    class SuccessfulTester:
        async def test(self, request: object) -> ProviderConnectionResult:
            return ProviderConnectionResult(available_models=["deepseek-v4-flash"])

    service = ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(
            base64.b64encode(bytes(range(32))).decode("ascii")
        ),
        connection_tester=SuccessfulTester(),
    )
    created = await service.create(
        ProviderConfigCreate(
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key=SecretStr("stage-five-canary-key"),
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds="60",
            max_concurrency=2,
            monthly_budget=None,
        )
    )
    await service.test_connection(created.id)
    await service.enable(created.id)

    disabled = await service.disable(created.id)

    assert disabled.status == "disabled"
    assert await service.list_teacher_models() == []
