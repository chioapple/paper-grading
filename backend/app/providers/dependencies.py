"""供应商配置的 FastAPI 依赖装配。"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_database_session
from app.providers.config import ProviderConfigRepository, ProviderConfigService
from app.providers.connection import (
    HttpCoreProviderClient,
    ProviderBaseUrlPolicy,
    ProviderConnectionTester,
)
from app.providers.repository import SqlAlchemyProviderConfigRepository
from app.security.encryption import ApiKeyCipher


def get_provider_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> ProviderConfigRepository:
    """创建当前请求的供应商配置仓库。"""

    return SqlAlchemyProviderConfigRepository(session)


def get_provider_service(
    request: Request,
    repository: Annotated[ProviderConfigRepository, Depends(get_provider_repository)],
) -> ProviderConfigService:
    """装配加密、SSRF 防护和连接测试能力。"""

    settings = request.app.state.settings
    url_policy = ProviderBaseUrlPolicy(
        allow_official_fake_ip=settings.allow_official_provider_fake_ip,
    )
    return ProviderConfigService(
        repository=repository,
        cipher=ApiKeyCipher.from_base64_master_key(settings.provider_master_key.get_secret_value()),
        connection_tester=ProviderConnectionTester(
            url_policy=url_policy,
            http_client=HttpCoreProviderClient(),
        ),
        url_policy=url_policy,
    )
