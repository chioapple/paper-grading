"""阶段十一教师复核 HTTP 公共契约。"""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_account
from app.auth.models import CurrentAccount
from app.config import Settings
from app.main import create_app
from app.reviews.dependencies import get_review_service
from app.reviews.models import ReviewJobSummary, ReviewQueueItem
from app.reviews.service import ReviewService, ReviewValidationError
from tests.auth_settings import TEST_AUTH_SETTINGS

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
ITEM_ID = UUID("33333333-3333-4333-8333-333333333333")
SUBMISSION_ID = UUID("44444444-4444-4444-8444-444444444444")
ASSIGNMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
ATTEMPT_ID = UUID("77777777-7777-4777-8777-777777777777")


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


def test_review_job_list_uses_human_readable_queue_rows() -> None:
    now = datetime(2026, 7, 19, tzinfo=UTC)

    class Service:
        async def list_jobs(self, owner_id: UUID) -> tuple[ReviewJobSummary, ...]:
            assert owner_id == OWNER_ID
            return (
                ReviewJobSummary(
                    id=JOB_ID,
                    assignment_id=ASSIGNMENT_ID,
                    assignment_title="Argumentative essay",
                    model="deepseek-v4-pro",
                    status="needs_review",
                    total=1,
                    needs_review=1,
                    completed=0,
                    failed=0,
                    items=(
                        ReviewQueueItem(
                            id=ITEM_ID,
                            submission_id=SUBMISSION_ID,
                            original_filename="essay-01.pdf",
                            position=0,
                            status="needs_review",
                            attempt_count=1,
                            error_code=None,
                            review_available=True,
                            review_id=None,
                            review_revision=None,
                            review_status=None,
                        ),
                    ),
                    created_at=now,
                    finished_at=None,
                ),
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_review_service] = lambda: cast(ReviewService, Service())

    with TestClient(application) as client:
        response = client.get("/grading-jobs")

    assert response.status_code == 200
    assert response.json()[0]["assignment_title"] == "Argumentative essay"
    assert response.json()[0]["items"][0]["original_filename"] == "essay-01.pdf"
    assert response.json()[0]["items"][0]["review_available"] is True


def test_review_validation_error_is_stable_and_does_not_echo_essay_text() -> None:
    class Service:
        async def save_draft(self, *_args: object, **_kwargs: object) -> object:
            raise ReviewValidationError(
                "review_evidence_quote_mismatch",
                "教师证据不是对应文本块中的逐字原文",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_review_service] = lambda: cast(ReviewService, Service())
    payload = {
        "attempt_id": str(ATTEMPT_ID),
        "criteria": [
            {
                "dimension_id": "argument",
                "score": "4",
                "reason": "Clear claim.",
                "revision_suggestions": ["Add support."],
            }
        ],
        "deductions": [],
        "evidence": [
            {
                "target_type": "dimension",
                "target_id": "argument",
                "block_id": "b000001",
                "quote": "private essay sentence",
            }
        ],
        "overall_feedback": "Add more support.",
        "change_reason": "Teacher correction.",
    }

    with TestClient(application) as client:
        response = client.put(
            f"/grading-jobs/{JOB_ID}/items/{ITEM_ID}/review",
            json=payload,
        )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "review_evidence_quote_mismatch"
    assert "private essay sentence" not in response.text


def test_stage_eleven_http_surface_exposes_complete_review_workflow() -> None:
    paths = create_app(build_test_settings()).openapi()["paths"]

    assert "get" in paths["/grading-jobs"]
    assert set(paths["/grading-jobs/{job_id}/items/{item_id}/review"]) == {"get", "put"}
    assert "post" in paths["/grading-jobs/{job_id}/items/{item_id}/review/confirm"]
    assert "post" in paths["/grading-jobs/{job_id}/reviews/batch-confirm"]
    assert "post" in paths["/grading-jobs/{job_id}/items/{item_id}/review/regrade"]
