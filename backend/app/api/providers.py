"""管理员供应商配置与教师模型目录接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import require_admin, require_teacher
from app.auth.models import CurrentAccount
from app.providers.config import (
    ProviderConfigCreate,
    ProviderConfigService,
    ProviderConfigUpdate,
    ProviderConfigView,
    ProviderTestResult,
    TeacherProviderModels,
)
from app.providers.dependencies import get_provider_service

router = APIRouter(tags=["providers"])


@router.get("/admin/providers", response_model=list[ProviderConfigView])
async def list_providers(
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> list[ProviderConfigView]:
    """列出供应商安全投影。"""

    return await service.list_configs()


@router.post(
    "/admin/providers",
    response_model=ProviderConfigView,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider(
    payload: ProviderConfigCreate,
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> ProviderConfigView:
    """创建一条不向浏览器回传 Key 的供应商配置。"""

    return await service.create(payload)


@router.put("/admin/providers/{provider_id}", response_model=ProviderConfigView)
async def update_provider(
    provider_id: UUID,
    payload: ProviderConfigUpdate,
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> ProviderConfigView:
    """更新配置；不传 API Key 时保留数据库中的密文。"""

    return await service.update(provider_id, payload)


@router.post(
    "/admin/providers/{provider_id}/test",
    response_model=ProviderTestResult,
)
async def test_provider_connection(
    provider_id: UUID,
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> ProviderTestResult:
    """使用当前配置执行无计费模型列表连接测试。"""

    return await service.test_connection(provider_id)


@router.post(
    "/admin/providers/{provider_id}/enable",
    response_model=ProviderConfigView,
)
async def enable_provider(
    provider_id: UUID,
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> ProviderConfigView:
    """只启用当前配置版本已测试通过的供应商。"""

    return await service.enable(provider_id)


@router.post(
    "/admin/providers/{provider_id}/disable",
    response_model=ProviderConfigView,
)
async def disable_provider(
    provider_id: UUID,
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> ProviderConfigView:
    """停用一个已启用供应商。"""

    return await service.disable(provider_id)


@router.get("/providers/models", response_model=list[TeacherProviderModels])
async def list_teacher_models(
    service: Annotated[ProviderConfigService, Depends(get_provider_service)],
    _teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> list[TeacherProviderModels]:
    """只向教师返回管理员已启用的允许模型。"""

    return await service.list_teacher_models()
