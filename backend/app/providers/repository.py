"""供应商配置的 PostgreSQL 持久化实现。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import ProviderConfig
from app.providers.config import ProviderConfigUpdateValues, StoredProviderConfig


class SqlAlchemyProviderConfigRepository:
    """在当前管理员请求事务中读写供应商配置。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_stored(config: ProviderConfig) -> StoredProviderConfig:
        return StoredProviderConfig.model_validate(config)

    async def create(self, config: StoredProviderConfig) -> StoredProviderConfig:
        row = ProviderConfig(
            id=config.id,
            provider_type=config.provider_type.value,
            name=config.name,
            base_url=config.base_url,
            encrypted_api_key=config.encrypted_api_key,
            api_key_nonce=config.api_key_nonce,
            allowed_models=config.allowed_models,
            default_model=config.default_model,
            timeout_seconds=config.timeout_seconds,
            max_concurrency=config.max_concurrency,
            monthly_budget=config.monthly_budget,
            model_profiles={
                model: profile.model_dump(mode="json")
                for model, profile in config.model_profiles.items()
            },
            status=config.status.value,
            config_version=config.config_version,
            tested_config_version=config.tested_config_version,
            tested_at=config.tested_at,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_stored(row)

    async def get(self, provider_id: UUID) -> StoredProviderConfig | None:
        row = await self._session.get(ProviderConfig, provider_id)
        return self._to_stored(row) if row is not None else None

    async def list_all(self) -> list[StoredProviderConfig]:
        rows = (
            await self._session.scalars(
                select(ProviderConfig).order_by(ProviderConfig.created_at, ProviderConfig.name)
            )
        ).all()
        return [self._to_stored(row) for row in rows]

    async def update(
        self,
        provider_id: UUID,
        *,
        expected_config_version: int,
        values: ProviderConfigUpdateValues,
    ) -> StoredProviderConfig | None:
        result = await self._session.execute(
            update(ProviderConfig)
            .where(
                ProviderConfig.id == provider_id,
                ProviderConfig.config_version == expected_config_version,
            )
            .values(**values.model_dump())
            .returning(ProviderConfig)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_stored(row)

    async def mark_tested(
        self,
        provider_id: UUID,
        *,
        expected_config_version: int,
        tested_at: datetime,
    ) -> StoredProviderConfig | None:
        result = await self._session.execute(
            update(ProviderConfig)
            .where(
                ProviderConfig.id == provider_id,
                ProviderConfig.config_version == expected_config_version,
            )
            .values(
                tested_at=tested_at,
                tested_config_version=expected_config_version,
            )
            .returning(ProviderConfig)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_stored(row)

    async def enable_tested(self, provider_id: UUID) -> StoredProviderConfig | None:
        result = await self._session.execute(
            update(ProviderConfig)
            .where(
                ProviderConfig.id == provider_id,
                ProviderConfig.encrypted_api_key.is_not(None),
                ProviderConfig.api_key_nonce.is_not(None),
                ProviderConfig.default_model.is_not(None),
                ProviderConfig.model_profiles.op("?")(ProviderConfig.default_model),
                ProviderConfig.tested_at.is_not(None),
                ProviderConfig.tested_config_version == ProviderConfig.config_version,
            )
            .values(status="enabled")
            .returning(ProviderConfig)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_stored(row)

    async def disable_enabled(self, provider_id: UUID) -> StoredProviderConfig | None:
        result = await self._session.execute(
            update(ProviderConfig)
            .where(ProviderConfig.id == provider_id, ProviderConfig.status == "enabled")
            .values(status="disabled")
            .returning(ProviderConfig)
        )
        row = result.scalar_one_or_none()
        if row is None:
            await self._session.rollback()
            return None
        await self._session.commit()
        await self._session.refresh(row)
        return self._to_stored(row)

    async def list_enabled(self) -> list[StoredProviderConfig]:
        rows = (
            await self._session.scalars(
                select(ProviderConfig)
                .where(
                    ProviderConfig.status == "enabled",
                    ProviderConfig.model_profiles.op("?")(ProviderConfig.default_model),
                )
                .order_by(ProviderConfig.name)
            )
        ).all()
        return [self._to_stored(row) for row in rows]
