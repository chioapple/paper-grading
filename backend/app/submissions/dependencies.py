"""阶段七论文服务的 FastAPI 依赖装配。"""

from fastapi import Request

from app.db import Database
from app.storage.supabase import SupabaseObjectStorage
from app.submissions.repository import SqlAlchemySubmissionRepository
from app.submissions.service import SubmissionService


def get_submission_service(request: Request) -> SubmissionService:
    """复用应用级 Supabase Storage 客户端，并为每次请求创建短事务仓储。"""

    database: Database = request.app.state.database
    storage: SupabaseObjectStorage = request.app.state.object_storage
    settings = request.app.state.settings
    return SubmissionService(
        repository=SqlAlchemySubmissionRepository(database),
        storage=storage,
        signed_url_ttl_seconds=settings.supabase_storage_signed_url_ttl_seconds,
    )
