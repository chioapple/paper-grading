"""阶段六作业与 Rubric HTTP 契约测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_account
from app.auth.models import CurrentAccount
from app.config import Settings
from app.main import create_app
from app.rubrics.dependencies import get_assignment_rubric_service
from app.rubrics.models import AssignmentCreate, AssignmentDetail, AssignmentSummary, RubricView
from app.rubrics.service import AssignmentRubricRepository, AssignmentRubricService
from tests.auth_settings import TEST_AUTH_SETTINGS

OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
ASSIGNMENT_ID = UUID("44444444-4444-4444-4444-444444444444")
RUBRIC_ID = UUID("55555555-5555-5555-5555-555555555555")


def build_test_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        **TEST_AUTH_SETTINGS,
    )


def test_zero_cost_runtime_does_not_construct_a_rubric_model_client() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                database=object(),
                settings=build_test_settings(),
            )
        )
    )

    service = get_assignment_rubric_service(request)  # type: ignore[arg-type]

    assert service._generator is None
    assert service._provider_calls_enabled is False


class CreateAssignmentRepository:
    def __init__(self) -> None:
        self.created: AssignmentDetail | None = None

    async def create_assignment(
        self,
        owner_id: UUID,
        payload: AssignmentCreate,
    ) -> AssignmentDetail:
        assert owner_id == OWNER_ID
        now = datetime(2026, 7, 16, tzinfo=UTC)
        rubric = RubricView(
            id=RUBRIC_ID,
            assignment_id=ASSIGNMENT_ID,
            version=1,
            status="draft",
            original_rubric=payload.original_rubric,
            structured_rubric=None,
            total_score=payload.total_score,
            score_step=payload.score_step,
            provider_config_id=None,
            model=None,
            confirmed_at=None,
            created_at=now,
        )
        self.created = AssignmentDetail(
            id=ASSIGNMENT_ID,
            title=payload.title,
            instructions=payload.instructions,
            status="draft",
            current_rubric_status="draft",
            current_rubric_version=1,
            current_draft_version=1,
            current_confirmed_version=None,
            current_draft={"id": RUBRIC_ID, "version": 1, "status": "draft"},
            current_confirmed=None,
            created_at=now,
            updated_at=now,
            rubric_versions=[rubric],
        )
        return self.created

    async def list_assignments(self, owner_id: UUID) -> list[AssignmentSummary]:
        assert owner_id == OWNER_ID
        if self.created is None:
            return []
        return [AssignmentSummary.model_validate(self.created)]


def teacher_account() -> CurrentAccount:
    return CurrentAccount(
        id=OWNER_ID,
        email="teacher@example.edu",
        display_name="张老师",
        role="teacher",
        status="active",
    )


def test_teacher_atomically_creates_and_lists_an_assignment_with_rubric_v1() -> None:
    repository = CreateAssignmentRepository()
    service = AssignmentRubricService(
        repository=cast(AssignmentRubricRepository, repository),
    )
    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_assignment_rubric_service] = lambda: service

    with TestClient(application) as client:
        created = client.post(
            "/assignments",
            json={
                "title": "Argumentative Essay",
                "instructions": "Write 800 words.",
                "original_rubric": "Thesis 100.",
                "total_score": "100",
                "score_step": "1",
            },
        )
        listed = client.get("/assignments")

    assert created.status_code == 201
    assert created.json()["rubric_versions"][0]["version"] == 1
    assert listed.status_code == 200
    assert listed.json()[0]["current_draft"] == {
        "id": str(RUBRIC_ID),
        "version": 1,
        "status": "draft",
    }


def test_stage_six_http_surface_exposes_the_complete_teacher_workflow() -> None:
    paths = create_app(build_test_settings()).openapi()["paths"]

    assert set(paths["/assignments"]) >= {"get", "post"}
    assert set(paths["/assignments/{assignment_id}"]) >= {"get", "put"}
    assert set(paths["/assignments/{assignment_id}/status"]) >= {"put"}
    assert set(paths["/assignments/{assignment_id}/rubrics"]) >= {"post"}
    assert set(paths["/assignments/{assignment_id}/rubrics/{rubric_id}"]) >= {"put"}
    assert set(paths["/assignments/{assignment_id}/rubrics/{rubric_id}/structure"]) >= {"post"}
    assert set(paths["/assignments/{assignment_id}/rubrics/{rubric_id}/confirm"]) >= {"post"}
