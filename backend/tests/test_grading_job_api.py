"""阶段十批次 HTTP 与 SSE 公共契约测试。"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_account
from app.auth.models import CurrentAccount
from app.config import Settings
from app.main import create_app
from app.monitoring.repository import QuotaExceededError, QuotaUnavailableError
from app.workers.dependencies import get_grading_job_service
from app.workers.models import GradingJobCreate, GradingJobItemView, GradingJobView
from app.workers.service import GradingJobConfigurationError
from tests.auth_settings import TEST_AUTH_SETTINGS

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
ASSIGNMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
ITEM_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("55555555-5555-5555-5555-555555555555")
RUBRIC_ID = UUID("66666666-6666-6666-6666-666666666666")


def build_test_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        **TEST_AUTH_SETTINGS,
    )


def teacher_account() -> CurrentAccount:
    return CurrentAccount(
        id=OWNER_ID,
        email="teacher@example.edu",
        display_name="张老师",
        role="teacher",
        status="active",
    )


def job_view(status: str = "queued") -> GradingJobView:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    item_status = "queued" if status == "queued" else "needs_review"
    return GradingJobView(
        id=JOB_ID,
        assignment_id=ASSIGNMENT_ID,
        rubric_version_id=RUBRIC_ID,
        model="deepseek-v4-pro",
        status=status,
        state_version=1 if status == "queued" else 2,
        total=1,
        queued=1 if item_status == "queued" else 0,
        running=0,
        needs_review=1 if item_status == "needs_review" else 0,
        completed=0,
        failed=0,
        cancelled=0,
        items=(
            GradingJobItemView(
                id=ITEM_ID,
                submission_id=SUBMISSION_ID,
                position=0,
                status=item_status,
                attempt_count=0 if item_status == "queued" else 1,
                error_code=None,
            ),
        ),
        started_at=None if status == "queued" else now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )


def test_teacher_creates_reads_and_streams_real_database_progress() -> None:
    class Service:
        async def create_job(
            self,
            owner_id: UUID,
            assignment_id: UUID,
            payload: GradingJobCreate,
        ) -> GradingJobView:
            assert owner_id == OWNER_ID
            assert assignment_id == ASSIGNMENT_ID
            assert payload.submission_ids == (SUBMISSION_ID,)
            assert payload.idempotency_key == "class-a-first-pass"
            return job_view()

        async def get_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView:
            assert owner_id == OWNER_ID
            assert job_id == JOB_ID
            return job_view("needs_review")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_grading_job_service] = Service

    with TestClient(application) as client:
        created = client.post(
            f"/assignments/{ASSIGNMENT_ID}/grading-jobs",
            headers={"Idempotency-Key": "class-a-first-pass"},
            json={"submission_ids": [str(SUBMISSION_ID)]},
        )
        fetched = client.get(f"/grading-jobs/{JOB_ID}")
        streamed = client.get(f"/grading-jobs/{JOB_ID}/events")

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert fetched.status_code == 200
    assert fetched.json()["needs_review"] == 1
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in streamed.text
    assert '"settled":true' in streamed.text
    assert "raw_response" not in streamed.text


def test_stage_ten_http_surface_exposes_batch_controls() -> None:
    paths = create_app(build_test_settings()).openapi()["paths"]

    assert "post" in paths["/assignments/{assignment_id}/grading-jobs"]
    assert "get" in paths["/grading-jobs/{job_id}"]
    assert "post" in paths["/grading-jobs/{job_id}/pause"]
    assert "post" in paths["/grading-jobs/{job_id}/resume"]
    assert "post" in paths["/grading-jobs/{job_id}/cancel"]
    assert "post" in paths["/grading-jobs/{job_id}/items/{item_id}/retry"]
    assert "get" in paths["/grading-jobs/{job_id}/events"]


def test_grading_job_configuration_error_exposes_a_stable_safe_code() -> None:
    class Service:
        async def create_job(
            self,
            _owner_id: UUID,
            _assignment_id: UUID,
            _payload: GradingJobCreate,
        ) -> GradingJobView:
            raise GradingJobConfigurationError(
                "供应商当前配置不可用于评分",
                code="grading_job_provider_invalid",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_grading_job_service] = Service

    with TestClient(application) as client:
        response = client.post(
            f"/assignments/{ASSIGNMENT_ID}/grading-jobs",
            headers={"Idempotency-Key": "configuration-error"},
            json={"submission_ids": [str(SUBMISSION_ID)]},
        )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "grading_job_provider_invalid",
            "message": "供应商当前配置不可用于评分",
        }
    }


def test_database_quota_block_returns_a_safe_growth_only_error() -> None:
    class Service:
        async def create_job(
            self,
            _owner_id: UUID,
            _assignment_id: UUID,
            _payload: GradingJobCreate,
        ) -> GradingJobView:
            raise QuotaExceededError(
                resource="database",
                code="database_quota_exceeded",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_grading_job_service] = Service

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(
            f"/assignments/{ASSIGNMENT_ID}/grading-jobs",
            headers={"Idempotency-Key": "database-quota-blocked"},
            json={"submission_ids": [str(SUBMISSION_ID)]},
        )

    assert response.status_code == 507
    assert response.json() == {
        "detail": {
            "code": "database_quota_exceeded",
            "message": "系统容量已达到安全上限，暂时不能创建新的评分批次",
        }
    }


def test_database_quota_sample_failure_returns_a_safe_retryable_error() -> None:
    class Service:
        async def create_job(
            self,
            _owner_id: UUID,
            _assignment_id: UUID,
            _payload: GradingJobCreate,
        ) -> GradingJobView:
            raise QuotaUnavailableError(
                resource="database",
                code="database_usage_unavailable",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_grading_job_service] = Service

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(
            f"/assignments/{ASSIGNMENT_ID}/grading-jobs",
            headers={"Idempotency-Key": "database-quota-unavailable"},
            json={"submission_ids": [str(SUBMISSION_ID)]},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "database_usage_unavailable",
            "message": "系统暂时无法确认剩余容量，请稍后重试",
        }
    }
