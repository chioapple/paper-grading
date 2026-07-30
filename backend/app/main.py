"""FastAPI 应用入口。"""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.admin_users import router as admin_users_router
from app.api.assignments import router as assignments_router
from app.api.auth import router as auth_router
from app.api.exports import router as exports_router
from app.api.grading_jobs import router as grading_jobs_router
from app.api.health import router as health_router
from app.api.providers import router as providers_router
from app.api.reviews import router as reviews_router
from app.api.rubrics import router as rubrics_router
from app.api.submissions import router as submissions_router
from app.auth.service import AccountStateError, AccountSyncError
from app.auth.supabase import SupabaseAuthError, SupabaseAuthGateway
from app.config import AppEnvironment, Settings
from app.db import Database
from app.export.service import (
    ExportDataError,
    ExportIdempotencyConflict,
    ExportNotFoundError,
    ExportStateError,
)
from app.http_limits import UploadBodyLimitMiddleware
from app.monitoring.repository import (
    QuotaExceededError,
    QuotaUnavailableError,
    SqlAlchemyQuotaRepository,
)
from app.parsing.models import DocumentParseError
from app.providers.config import (
    ProviderConfigurationError,
    ProviderNotFoundError,
    ProviderStateError,
)
from app.providers.connection import ProviderConnectionError, ProviderUrlError
from app.readiness import DatabaseReadinessProbe
from app.reviews.service import (
    ReviewConflictError,
    ReviewDataError,
    ReviewNotFoundError,
    ReviewStateError,
    ReviewValidationError,
)
from app.rubrics.generation import RubricGenerationError
from app.rubrics.service import (
    AssignmentNotFoundError,
    AssignmentStateError,
    RubricNotFoundError,
    RubricProviderUnavailableError,
    RubricStateError,
)
from app.security.encryption import EncryptedApiKeyError
from app.storage.supabase import SupabaseObjectStorage, SupabaseStorageError
from app.submissions.service import (
    SubmissionAssignmentNotFoundError,
    SubmissionAssignmentStateError,
    SubmissionNotFoundError,
    SubmissionTransitionError,
)
from app.workers.service import (
    GradingJobConfigurationError,
    GradingJobIdempotencyConflict,
    GradingJobNotFoundError,
    GradingJobStateError,
)

logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用；配置在启动阶段校验，失败时直接终止启动。"""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings or Settings.load()
        database = Database.from_settings(runtime_settings)
        try:
            async with (
                httpx.AsyncClient(
                    timeout=runtime_settings.supabase_auth_timeout_seconds,
                    trust_env=False,
                ) as auth_client,
                httpx.AsyncClient(
                    timeout=runtime_settings.supabase_storage_timeout_seconds,
                    limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
                    trust_env=False,
                ) as storage_client,
            ):
                auth_gateway = SupabaseAuthGateway(
                    base_url=runtime_settings.supabase_url,
                    publishable_key=runtime_settings.supabase_publishable_key,
                    secret_key=runtime_settings.supabase_secret_key.get_secret_value(),
                    invite_redirect_url=runtime_settings.auth_invite_redirect_url,
                    client=auth_client,
                )
                if runtime_settings.app_env is AppEnvironment.PRODUCTION:
                    await auth_gateway.require_public_signup_disabled()
                application.state.settings = runtime_settings
                application.state.database = database
                application.state.auth_gateway = auth_gateway
                application.state.readiness_probe = DatabaseReadinessProbe(
                    engine=database.engine,
                    timeout_seconds=runtime_settings.readiness_database_timeout_seconds,
                )
                application.state.object_storage = SupabaseObjectStorage.from_settings(
                    runtime_settings,
                    storage_client,
                    quota=SqlAlchemyQuotaRepository(database),
                )
                yield
        finally:
            await database.dispose()

    application = FastAPI(
        title="Paper Grading API",
        version="0.1.0",
        lifespan=lifespan,
    )
    frontend_origin = (
        settings.frontend_origin if settings else os.environ.get("FRONTEND_ORIGIN", "")
    )
    application.add_middleware(UploadBodyLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin] if frontend_origin else [],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )

    @application.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """为所有 API 响应添加固定浏览器安全头。"""

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        safe_errors = [
            {
                "type": item["type"],
                "location": list(item["loc"]),
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "request_validation_failed",
                    "message": "请求数据无效",
                    "errors": safe_errors,
                }
            },
        )

    @application.exception_handler(AccountStateError)
    async def handle_account_state_error(
        _request: Request,
        _error: AccountStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "account_state_conflict",
                    "message": "账户状态已变化",
                }
            },
        )

    @application.exception_handler(AccountSyncError)
    async def handle_account_sync_error(
        _request: Request,
        _error: AccountSyncError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "code": "account_sync_failed",
                    "message": "账户数据同步失败",
                }
            },
        )

    @application.exception_handler(SupabaseAuthError)
    async def handle_supabase_auth_error(
        _request: Request,
        _error: SupabaseAuthError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "code": "auth_provider_unavailable",
                    "message": "认证服务暂时不可用",
                }
            },
        )

    @application.exception_handler(ProviderNotFoundError)
    async def handle_provider_not_found(
        _request: Request,
        _error: ProviderNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "provider_not_found", "message": "供应商配置不存在"}},
        )

    @application.exception_handler(GradingJobNotFoundError)
    async def handle_grading_job_not_found(
        _request: Request,
        _error: GradingJobNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "grading_job_not_found", "message": "评分批次不存在"}},
        )

    @application.exception_handler(GradingJobIdempotencyConflict)
    async def handle_grading_job_idempotency_conflict(
        _request: Request,
        _error: GradingJobIdempotencyConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "grading_job_idempotency_conflict",
                    "message": "幂等键已用于不同批次请求",
                }
            },
        )

    @application.exception_handler(GradingJobStateError)
    async def handle_grading_job_state_error(
        _request: Request,
        _error: GradingJobStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "grading_job_state_conflict",
                    "message": "评分批次状态不允许当前操作",
                }
            },
        )

    @application.exception_handler(GradingJobConfigurationError)
    async def handle_grading_job_configuration_error(
        _request: Request,
        error: GradingJobConfigurationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": error.code,
                    "message": str(error),
                }
            },
        )

    @application.exception_handler(QuotaExceededError)
    async def handle_quota_exceeded(
        _request: Request,
        error: QuotaExceededError,
    ) -> JSONResponse:
        message = (
            "系统容量已达到安全上限，暂时不能创建新的评分批次"
            if error.resource == "database"
            else "文件存储容量已达到安全上限，暂时不能继续上传"
        )
        return JSONResponse(
            status_code=507,
            content={"detail": {"code": error.code, "message": message}},
        )

    @application.exception_handler(QuotaUnavailableError)
    async def handle_quota_unavailable(
        _request: Request,
        error: QuotaUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": error.code,
                    "message": "系统暂时无法确认剩余容量，请稍后重试",
                }
            },
        )

    @application.exception_handler(ExportNotFoundError)
    async def handle_export_not_found(
        _request: Request,
        _error: ExportNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "export_not_found", "message": "导出不存在"}},
        )

    @application.exception_handler(ExportIdempotencyConflict)
    async def handle_export_idempotency_conflict(
        _request: Request,
        _error: ExportIdempotencyConflict,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "export_idempotency_conflict",
                    "message": "幂等键已用于不同导出请求",
                }
            },
        )

    @application.exception_handler(ExportStateError)
    async def handle_export_state_error(
        _request: Request,
        error: ExportStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"code": "export_state_conflict", "message": str(error)}},
        )

    @application.exception_handler(ExportDataError)
    async def handle_export_data_error(
        _request: Request,
        error: ExportDataError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"code": error.code, "message": str(error)}},
        )

    @application.exception_handler(ReviewNotFoundError)
    async def handle_review_not_found(
        _request: Request,
        _error: ReviewNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "review_not_found", "message": "复核任务不存在"}},
        )

    @application.exception_handler(ReviewStateError)
    async def handle_review_state_error(
        _request: Request,
        _error: ReviewStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "review_state_conflict",
                    "message": "复核状态已变化，请刷新后重试",
                }
            },
        )

    @application.exception_handler(ReviewConflictError)
    async def handle_review_conflict_error(
        _request: Request,
        _error: ReviewConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "review_concurrent_conflict",
                    "message": "复核已被另一请求修改，请刷新后重试",
                }
            },
        )

    @application.exception_handler(ReviewValidationError)
    async def handle_review_validation_error(
        _request: Request,
        error: ReviewValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": error.code, "message": str(error)}},
        )

    @application.exception_handler(ReviewDataError)
    async def handle_review_data_error(
        _request: Request,
        error: ReviewDataError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"code": error.code, "message": str(error)}},
        )

    @application.exception_handler(ProviderStateError)
    async def handle_provider_state_error(
        _request: Request,
        error: ProviderStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": {"code": "provider_state_conflict", "message": str(error)}},
        )

    @application.exception_handler(ProviderUrlError)
    async def handle_provider_url_error(
        _request: Request,
        error: ProviderUrlError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "provider_url_rejected", "message": str(error)}},
        )

    @application.exception_handler(ProviderConfigurationError)
    async def handle_provider_configuration_error(
        _request: Request,
        error: ProviderConfigurationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "provider_configuration_invalid", "message": str(error)}},
        )

    @application.exception_handler(ProviderConnectionError)
    async def handle_provider_connection_error(
        _request: Request,
        error: ProviderConnectionError,
    ) -> JSONResponse:
        status_code = {
            "provider_authentication_failed": 422,
            "provider_balance_unavailable": 409,
            "provider_rate_limited": 429,
            "provider_connection_timeout": 504,
            "provider_unavailable": 502,
        }.get(error.code, 422)
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": error.code, "message": str(error)}},
        )

    @application.exception_handler(EncryptedApiKeyError)
    async def handle_encrypted_api_key_error(
        _request: Request,
        _error: EncryptedApiKeyError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "provider_key_material_invalid",
                    "message": "供应商密钥材料无法验证",
                }
            },
        )

    @application.exception_handler(AssignmentNotFoundError)
    async def handle_assignment_not_found(
        _request: Request,
        _error: AssignmentNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "assignment_not_found", "message": "作业不存在"}},
        )

    @application.exception_handler(RubricNotFoundError)
    async def handle_rubric_not_found(
        _request: Request,
        _error: RubricNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "rubric_not_found", "message": "Rubric 版本不存在"}},
        )

    @application.exception_handler(AssignmentStateError)
    async def handle_assignment_state_error(
        _request: Request,
        _error: AssignmentStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "assignment_state_conflict",
                    "message": "作业状态已变化",
                }
            },
        )

    @application.exception_handler(RubricStateError)
    async def handle_rubric_state_error(
        _request: Request,
        _error: RubricStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "rubric_state_conflict",
                    "message": "Rubric 状态已变化",
                }
            },
        )

    @application.exception_handler(RubricProviderUnavailableError)
    async def handle_rubric_provider_unavailable(
        _request: Request,
        _error: RubricProviderUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "rubric_provider_unavailable",
                    "message": "所选供应商当前不可用于生成",
                }
            },
        )

    @application.exception_handler(RubricGenerationError)
    async def handle_rubric_generation_error(
        _request: Request,
        error: RubricGenerationError,
    ) -> JSONResponse:
        status_code = {
            "rubric_provider_unsupported": 422,
            "rubric_provider_balance_unavailable": 409,
            "rubric_provider_rate_limited": 429,
            "rubric_provider_timeout": 504,
        }.get(error.code, 502)
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": error.code, "message": str(error)}},
        )

    @application.exception_handler(DocumentParseError)
    async def handle_document_parse_error(
        _request: Request,
        error: DocumentParseError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=413 if error.code == "file_too_large" else 422,
            content={"detail": {"code": error.code, "message": str(error)}},
        )

    @application.exception_handler(SubmissionAssignmentNotFoundError)
    async def handle_submission_assignment_not_found(
        _request: Request,
        _error: SubmissionAssignmentNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "assignment_not_found", "message": "作业不存在"}},
        )

    @application.exception_handler(SubmissionAssignmentStateError)
    async def handle_submission_assignment_state(
        _request: Request,
        _error: SubmissionAssignmentStateError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "assignment_not_ready",
                    "message": "请先确认作业评分标准",
                }
            },
        )

    @application.exception_handler(SubmissionNotFoundError)
    async def handle_submission_not_found(
        _request: Request,
        _error: SubmissionNotFoundError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": {"code": "submission_not_found", "message": "论文不存在"}},
        )

    @application.exception_handler(SubmissionTransitionError)
    async def handle_submission_transition_error(
        _request: Request,
        _error: SubmissionTransitionError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "submission_state_conflict",
                    "message": "论文状态已变化，请刷新后重试",
                }
            },
        )

    @application.exception_handler(SupabaseStorageError)
    async def handle_supabase_storage_error(
        _request: Request,
        _error: SupabaseStorageError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "detail": {
                    "code": "object_storage_unavailable",
                    "message": "文件存储暂时不可用",
                }
            },
        )

    application.include_router(admin_users_router)
    application.include_router(assignments_router)
    application.include_router(auth_router)
    application.include_router(exports_router)
    application.include_router(health_router)
    application.include_router(grading_jobs_router)
    application.include_router(providers_router)
    application.include_router(reviews_router)
    application.include_router(rubrics_router)
    application.include_router(submissions_router)
    return application


app = create_app()
