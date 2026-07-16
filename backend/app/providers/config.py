"""供应商配置的业务模型与状态规则。"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.domain.enums import ProviderStatus, ProviderType
from app.providers.connection import (
    OFFICIAL_BASE_URLS,
    ProviderBaseUrlPolicy,
    ProviderConnectionRequest,
    ProviderConnectionResult,
)
from app.security.encryption import ApiKeyCipher, EncryptedApiKey


class ProviderConfigurationError(ValueError):
    """供应商配置不满足业务规则。"""


class ProviderNotFoundError(LookupError):
    """供应商配置不存在。"""


class ProviderStateError(RuntimeError):
    """供应商状态或配置版本已经变化。"""


def _normalize_api_key(value: SecretStr) -> SecretStr:
    normalized = value.get_secret_value().strip()
    if not normalized:
        raise ValueError("API Key 不能为空")
    if any(not 33 <= ord(character) <= 126 for character in normalized):
        raise ValueError("API Key 必须只包含无空格的可打印 ASCII 字符")
    return SecretStr(normalized)


class ProviderConfigCreate(BaseModel):
    """管理员创建供应商配置所需字段。"""

    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr = Field(min_length=1, max_length=4096)
    allowed_models: list[str] = Field(min_length=1, max_length=100)
    default_model: str = Field(min_length=1, max_length=255)
    timeout_seconds: Decimal = Field(gt=0, le=300, max_digits=8, decimal_places=3)
    max_concurrency: int = Field(ge=1, le=100)
    monthly_budget: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )

    @field_validator("name", "default_model")
    @classmethod
    def normalize_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: SecretStr) -> SecretStr:
        return _normalize_api_key(value)

    @field_validator("allowed_models")
    @classmethod
    def normalize_allowed_models(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("允许模型不得包含空值")
        if len(set(normalized)) != len(normalized):
            raise ValueError("允许模型不得重复")
        return normalized

    @model_validator(mode="after")
    def validate_default_model(self) -> Self:
        if self.default_model not in self.allowed_models:
            raise ValueError("默认模型必须包含在允许模型中")
        return self


class ProviderConfigUpdate(BaseModel):
    """管理员更新供应商配置；未提供 API Key 时保留原密钥。"""

    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=4096)
    allowed_models: list[str] | None = Field(default=None, min_length=1, max_length=100)
    default_model: str | None = Field(default=None, min_length=1, max_length=255)
    timeout_seconds: Decimal | None = Field(
        default=None,
        gt=0,
        le=300,
        max_digits=8,
        decimal_places=3,
    )
    max_concurrency: int | None = Field(default=None, ge=1, le=100)
    monthly_budget: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )

    @field_validator("name", "default_model")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("字段不能为空")
        return normalized

    @field_validator("base_url")
    @classmethod
    def normalize_optional_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def normalize_optional_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        return _normalize_api_key(value)

    @field_validator("allowed_models")
    @classmethod
    def normalize_optional_models(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return ProviderConfigCreate.normalize_allowed_models(values)


class ProviderConfigUpdateValues(BaseModel):
    """仓库一次原子更新所需的完整字段。"""

    provider_type: ProviderType
    name: str
    base_url: str
    encrypted_api_key: bytes = Field(repr=False)
    api_key_nonce: bytes = Field(repr=False)
    allowed_models: list[str]
    default_model: str
    timeout_seconds: Decimal
    max_concurrency: int
    monthly_budget: Decimal | None


class StoredProviderConfig(BaseModel):
    """数据库内部记录；密钥材料不得直接作为 API 响应。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)

    id: UUID
    provider_type: ProviderType
    name: str
    base_url: str
    encrypted_api_key: bytes | None = Field(repr=False)
    api_key_nonce: bytes | None = Field(repr=False)
    allowed_models: list[str]
    default_model: str | None
    timeout_seconds: Decimal
    max_concurrency: int
    monthly_budget: Decimal | None
    status: ProviderStatus
    config_version: int
    tested_config_version: int | None
    tested_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProviderConfigView(BaseModel):
    """管理员可见的供应商安全投影。"""

    id: UUID
    provider_type: ProviderType
    name: str
    base_url: str
    api_key_configured: bool
    allowed_models: list[str]
    default_model: str | None
    timeout_seconds: Decimal
    max_concurrency: int
    monthly_budget: Decimal | None
    status: ProviderStatus
    configuration_tested: bool
    can_enable: bool
    tested_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_stored(cls, config: StoredProviderConfig) -> ProviderConfigView:
        configuration_tested = (
            config.tested_at is not None and config.tested_config_version == config.config_version
        )
        return cls(
            id=config.id,
            provider_type=config.provider_type,
            name=config.name,
            base_url=config.base_url,
            api_key_configured=(
                config.encrypted_api_key is not None and config.api_key_nonce is not None
            ),
            allowed_models=config.allowed_models,
            default_model=config.default_model,
            timeout_seconds=config.timeout_seconds,
            max_concurrency=config.max_concurrency,
            monthly_budget=config.monthly_budget,
            status=config.status,
            configuration_tested=configuration_tested,
            can_enable=(
                configuration_tested
                and config.encrypted_api_key is not None
                and config.api_key_nonce is not None
                and config.default_model is not None
            ),
            tested_at=config.tested_at,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


class ProviderTestResult(BaseModel):
    """连接成功后的安全结果。"""

    provider: ProviderConfigView
    available_models: list[str]


class TeacherProviderModels(BaseModel):
    """教师可见的已启用模型目录。"""

    provider_id: UUID
    provider_name: str
    provider_type: ProviderType
    allowed_models: list[str]
    default_model: str


class ProviderConnectionGateway(Protocol):
    """供应商外部连接测试边界。"""

    async def test(self, request: ProviderConnectionRequest) -> ProviderConnectionResult: ...


class ProviderConfigRepository(Protocol):
    """供应商配置持久化边界。"""

    async def create(self, config: StoredProviderConfig) -> StoredProviderConfig: ...

    async def list_all(self) -> list[StoredProviderConfig]: ...

    async def get(self, provider_id: UUID) -> StoredProviderConfig | None: ...

    async def mark_tested(
        self,
        provider_id: UUID,
        *,
        expected_config_version: int,
        tested_at: datetime,
    ) -> StoredProviderConfig | None: ...

    async def enable_tested(self, provider_id: UUID) -> StoredProviderConfig | None: ...

    async def update(
        self,
        provider_id: UUID,
        *,
        expected_config_version: int,
        values: ProviderConfigUpdateValues,
    ) -> StoredProviderConfig | None: ...

    async def list_enabled(self) -> list[StoredProviderConfig]: ...

    async def disable_enabled(self, provider_id: UUID) -> StoredProviderConfig | None: ...


class ProviderConfigService:
    """管理员供应商配置用例。"""

    def __init__(
        self,
        *,
        repository: ProviderConfigRepository,
        cipher: ApiKeyCipher,
        connection_tester: ProviderConnectionGateway | None = None,
        url_policy: ProviderBaseUrlPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._connection_tester = connection_tester
        self._url_policy = url_policy or ProviderBaseUrlPolicy()

    async def create(self, payload: ProviderConfigCreate) -> ProviderConfigView:
        expected_base_url = OFFICIAL_BASE_URLS.get(payload.provider_type)
        if expected_base_url is not None and payload.base_url != expected_base_url:
            raise ProviderConfigurationError("内置供应商必须使用官方 Base URL")
        if payload.provider_type is ProviderType.OPENAI_COMPATIBLE:
            validated = await self._url_policy.validate(payload.provider_type, payload.base_url)
            payload = payload.model_copy(update={"base_url": validated.value})

        provider_id = uuid4()
        encrypted = self._cipher.encrypt(
            payload.api_key.get_secret_value(),
            provider_id=provider_id,
        )
        now = datetime.now(UTC)
        stored = StoredProviderConfig(
            id=provider_id,
            provider_type=payload.provider_type,
            name=payload.name,
            base_url=payload.base_url,
            encrypted_api_key=encrypted.ciphertext,
            api_key_nonce=encrypted.nonce,
            allowed_models=payload.allowed_models,
            default_model=payload.default_model,
            timeout_seconds=payload.timeout_seconds,
            max_concurrency=payload.max_concurrency,
            monthly_budget=payload.monthly_budget,
            status=ProviderStatus.DRAFT,
            config_version=1,
            tested_config_version=None,
            tested_at=None,
            created_at=now,
            updated_at=now,
        )
        return ProviderConfigView.from_stored(await self._repository.create(stored))

    async def list_configs(self) -> list[ProviderConfigView]:
        configs = await self._repository.list_all()
        return [ProviderConfigView.from_stored(config) for config in configs]

    async def test_connection(self, provider_id: UUID) -> ProviderTestResult:
        config = await self._repository.get(provider_id)
        if config is None:
            raise ProviderNotFoundError("供应商配置不存在")
        if self._connection_tester is None:
            raise RuntimeError("供应商连接测试器尚未配置")
        if (
            config.encrypted_api_key is None
            or config.api_key_nonce is None
            or config.default_model is None
        ):
            raise ProviderStateError("供应商 Key 和默认模型尚未配置")
        api_key = self._cipher.decrypt(
            EncryptedApiKey(
                ciphertext=config.encrypted_api_key,
                nonce=config.api_key_nonce,
            ),
            provider_id=config.id,
        )
        result = await self._connection_tester.test(
            ProviderConnectionRequest(
                provider_type=config.provider_type,
                base_url=config.base_url,
                api_key=api_key,
                default_model=config.default_model,
                timeout_seconds=config.timeout_seconds,
            )
        )
        tested_at = datetime.now(UTC)
        tested = await self._repository.mark_tested(
            provider_id,
            expected_config_version=config.config_version,
            tested_at=tested_at,
        )
        if tested is None:
            raise ProviderStateError("连接测试期间供应商配置已变化")
        return ProviderTestResult(
            provider=ProviderConfigView.from_stored(tested),
            available_models=result.available_models,
        )

    async def enable(self, provider_id: UUID) -> ProviderConfigView:
        enabled = await self._repository.enable_tested(provider_id)
        if enabled is None:
            raise ProviderStateError("只有当前配置测试通过后才能启用")
        return ProviderConfigView.from_stored(enabled)

    async def disable(self, provider_id: UUID) -> ProviderConfigView:
        disabled = await self._repository.disable_enabled(provider_id)
        if disabled is None:
            raise ProviderStateError("只有已启用供应商可以停用")
        return ProviderConfigView.from_stored(disabled)

    async def update(
        self,
        provider_id: UUID,
        payload: ProviderConfigUpdate,
    ) -> ProviderConfigView:
        current = await self._repository.get(provider_id)
        if current is None:
            raise ProviderNotFoundError("供应商配置不存在")

        fields_set = payload.model_fields_set
        has_new_api_key = "api_key" in fields_set and payload.api_key is not None
        provider_type = payload.provider_type or current.provider_type
        name = payload.name or current.name
        base_url = payload.base_url or current.base_url
        allowed_models = payload.allowed_models or current.allowed_models
        default_model = payload.default_model or current.default_model
        timeout_seconds = payload.timeout_seconds or current.timeout_seconds
        max_concurrency = payload.max_concurrency or current.max_concurrency
        monthly_budget = (
            payload.monthly_budget if "monthly_budget" in fields_set else current.monthly_budget
        )
        if default_model is None:
            raise ProviderConfigurationError("默认模型尚未配置")
        if default_model not in allowed_models:
            raise ProviderConfigurationError("默认模型必须包含在允许模型中")
        expected_base_url = OFFICIAL_BASE_URLS.get(provider_type)
        if expected_base_url is not None and base_url != expected_base_url:
            raise ProviderConfigurationError("内置供应商必须使用官方 Base URL")
        if provider_type is ProviderType.OPENAI_COMPATIBLE:
            validated = await self._url_policy.validate(provider_type, base_url)
            base_url = validated.value

        if has_new_api_key:
            assert payload.api_key is not None
            api_key = payload.api_key.get_secret_value()
            encrypted = self._cipher.encrypt(api_key, provider_id=current.id)
            encrypted_api_key = encrypted.ciphertext
            api_key_nonce = encrypted.nonce
        else:
            assert current.encrypted_api_key is not None
            assert current.api_key_nonce is not None
            encrypted_api_key = current.encrypted_api_key
            api_key_nonce = current.api_key_nonce
        updated = await self._repository.update(
            provider_id,
            expected_config_version=current.config_version,
            values=ProviderConfigUpdateValues(
                provider_type=provider_type,
                name=name,
                base_url=base_url,
                encrypted_api_key=encrypted_api_key,
                api_key_nonce=api_key_nonce,
                allowed_models=allowed_models,
                default_model=default_model,
                timeout_seconds=timeout_seconds,
                max_concurrency=max_concurrency,
                monthly_budget=monthly_budget,
            ),
        )
        if updated is None:
            raise ProviderStateError("更新期间供应商配置已变化")
        return ProviderConfigView.from_stored(updated)

    async def list_teacher_models(self) -> list[TeacherProviderModels]:
        configs = await self._repository.list_enabled()
        catalog: list[TeacherProviderModels] = []
        for config in configs:
            if config.default_model is None:
                raise ProviderStateError("已启用供应商缺少默认模型")
            catalog.append(
                TeacherProviderModels(
                    provider_id=config.id,
                    provider_name=config.name,
                    provider_type=config.provider_type,
                    allowed_models=config.allowed_models,
                    default_model=config.default_model,
                )
            )
        return catalog
