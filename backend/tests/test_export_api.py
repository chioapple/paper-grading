"""阶段十二导出 HTTP 安全表面。"""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_account
from app.auth.models import CurrentAccount
from app.config import Settings
from app.export.dependencies import get_export_service
from app.export.models import ExportCreation, ExportView
from app.export.service import ExportNotFoundError, ExportService
from app.main import create_app
from tests.auth_settings import TEST_AUTH_SETTINGS

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
EXPORT_ID = UUID("33333333-3333-4333-8333-333333333333")
ASSIGNMENT_ID = UUID("44444444-4444-4444-8444-444444444444")


def settings() -> Settings:
    return Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        **TEST_AUTH_SETTINGS,
    )


def account() -> CurrentAccount:
    return CurrentAccount(
        id=OWNER_ID,
        email="teacher@example.edu",
        display_name="Teacher",
        role="teacher",
        status="active",
    )


def view() -> ExportView:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    return ExportView(
        id=EXPORT_ID,
        assignment_id=ASSIGNMENT_ID,
        grading_job_id=JOB_ID,
        assignment_title="Argumentative essay",
        export_type="draft",
        status="queued",
        paper_count=1,
        source_counts={"ai_suggestion": 1},
        safe_filename=None,
        error_code=None,
        snapshot_at=now,
        started_at=None,
        finished_at=None,
        created_at=now,
    )


def test_create_export_requires_idempotency_key_and_hides_internal_fields() -> None:
    class Service:
        async def create(self, owner_id: UUID, payload: object, key: str) -> ExportCreation:
            assert owner_id == OWNER_ID
            assert key == "one-click"
            return ExportCreation(export=view(), created=True)

    application = create_app(settings())
    application.dependency_overrides[get_current_account] = account
    application.dependency_overrides[get_export_service] = lambda: cast(ExportService, Service())
    with TestClient(application) as client:
        response = client.post(
            "/exports",
            headers={"Idempotency-Key": "one-click"},
            json={"grading_job_id": str(JOB_ID), "export_type": "draft"},
        )

    assert response.status_code == 201
    assert "object_key" not in response.text
    assert "file_sha256" not in response.text


def test_stage_twelve_http_surface_is_complete() -> None:
    paths = create_app(settings()).openapi()["paths"]
    assert set(paths["/exports"]) == {"get", "post"}
    assert "get" in paths["/exports/{export_id}"]
    assert "post" in paths["/exports/{export_id}/download"]


def test_create_export_hides_missing_and_cross_teacher_jobs_as_not_found() -> None:
    class Service:
        async def create(self, *_args: object) -> ExportCreation:
            raise ExportNotFoundError

    application = create_app(settings())
    application.dependency_overrides[get_current_account] = account
    application.dependency_overrides[get_export_service] = lambda: cast(ExportService, Service())
    with TestClient(application) as client:
        response = client.post(
            "/exports",
            headers={"Idempotency-Key": "hidden-job"},
            json={"grading_job_id": str(JOB_ID), "export_type": "draft"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "export_not_found", "message": "导出不存在"}}
