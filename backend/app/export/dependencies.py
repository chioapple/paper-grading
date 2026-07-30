"""阶段十二导出服务的 FastAPI 装配。"""

from typing import cast

from fastapi import Request

from app.db import Database
from app.export.dispatcher import CeleryExportQueue
from app.export.repository import SqlAlchemyExportRepository
from app.export.service import ExportDownloadStorage, ExportService


def get_export_service(request: Request) -> ExportService:
    database: Database = request.app.state.database
    return ExportService(
        repository=SqlAlchemyExportRepository(database),
        queue=CeleryExportQueue(),
        storage=cast(ExportDownloadStorage, request.app.state.object_storage),
        signed_url_ttl_seconds=request.app.state.settings.supabase_storage_signed_url_ttl_seconds,
    )
