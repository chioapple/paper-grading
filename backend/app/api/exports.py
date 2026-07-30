"""阶段十二 Excel 导出接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status

from app.auth.dependencies import require_teacher
from app.auth.models import CurrentAccount
from app.export.dependencies import get_export_service
from app.export.models import ExportCreateInput, ExportDownload, ExportView
from app.export.service import ExportService

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("", response_model=ExportView, status_code=status.HTTP_201_CREATED)
async def create_export(
    payload: ExportCreateInput,
    response: Response,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    service: Annotated[ExportService, Depends(get_export_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ExportView:
    creation = await service.create(teacher.id, payload, idempotency_key)
    if not creation.created:
        response.status_code = status.HTTP_200_OK
    return creation.export


@router.get("", response_model=tuple[ExportView, ...])
async def list_exports(
    service: Annotated[ExportService, Depends(get_export_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> tuple[ExportView, ...]:
    return await service.list(teacher.id)


@router.get("/{export_id}", response_model=ExportView)
async def get_export(
    export_id: UUID,
    service: Annotated[ExportService, Depends(get_export_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ExportView:
    return await service.get(teacher.id, export_id)


@router.post("/{export_id}/download", response_model=ExportDownload)
async def create_export_download(
    export_id: UUID,
    service: Annotated[ExportService, Depends(get_export_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ExportDownload:
    return await service.download(teacher.id, export_id)
