"""阶段七论文上传 HTTP 契约测试。"""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_account
from app.auth.models import CurrentAccount
from app.config import Settings
from app.http_limits import MAX_SUBMISSION_FILE_BYTES, MAX_SUBMISSION_REQUEST_BYTES
from app.main import create_app
from app.submissions.dependencies import get_submission_service
from app.submissions.models import (
    IncomingSubmission,
    SubmissionDownload,
    SubmissionUploadResult,
    SubmissionView,
)
from app.submissions.service import SubmissionService
from tests.auth_settings import TEST_AUTH_SETTINGS

OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
ASSIGNMENT_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("77777777-7777-7777-7777-777777777777")


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


def ready_submission() -> SubmissionView:
    return SubmissionView(
        id=SUBMISSION_ID,
        assignment_id=ASSIGNMENT_ID,
        original_filename="essay.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size_bytes=12,
        status="ready",
        error_code=None,
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
    )


class RecordingSubmissionService:
    def __init__(self) -> None:
        self.received: bytes | None = None
        self.upload_calls = 0

    async def upload_submission(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        incoming: IncomingSubmission,
    ) -> SubmissionUploadResult:
        self.upload_calls += 1
        assert owner_id == OWNER_ID
        assert assignment_id == ASSIGNMENT_ID
        assert incoming.original_filename == "essay.docx"
        self.received = incoming.stream.read()
        return SubmissionUploadResult(duplicate=False, submission=ready_submission())

    async def list_submissions(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> list[SubmissionView]:
        assert owner_id == OWNER_ID
        assert assignment_id == ASSIGNMENT_ID
        return [ready_submission()]

    async def create_download(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        submission_id: UUID,
    ) -> SubmissionDownload:
        assert owner_id == OWNER_ID
        assert assignment_id == ASSIGNMENT_ID
        assert submission_id == SUBMISSION_ID
        return SubmissionDownload(
            url="https://signed.example.test/object",
            expires_in_seconds=60,
        )


def test_teacher_uploads_lists_and_requests_a_private_submission_download() -> None:
    service = RecordingSubmissionService()
    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_submission_service] = lambda: cast(
        SubmissionService,
        service,
    )

    with TestClient(application) as client:
        uploaded = client.post(
            f"/assignments/{ASSIGNMENT_ID}/submissions",
            files={
                "file": (
                    "essay.docx",
                    b"test-content",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        listed = client.get(f"/assignments/{ASSIGNMENT_ID}/submissions")
        download = client.post(f"/assignments/{ASSIGNMENT_ID}/submissions/{SUBMISSION_ID}/download")

    assert uploaded.status_code == 200
    assert uploaded.json()["submission"]["status"] == "ready"
    assert service.received == b"test-content"
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == str(SUBMISSION_ID)
    assert download.status_code == 200
    assert download.json() == {
        "url": "https://signed.example.test/object",
        "expires_in_seconds": 60,
    }


def test_stage_seven_http_surface_exposes_submission_workflow() -> None:
    paths = create_app(build_test_settings()).openapi()["paths"]

    assert set(paths["/assignments/{assignment_id}/submissions"]) >= {"get", "post"}
    assert set(paths["/assignments/{assignment_id}/submissions/{submission_id}/download"]) >= {
        "post"
    }


def test_declared_oversized_submission_never_reaches_service() -> None:
    service = RecordingSubmissionService()
    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_submission_service] = lambda: cast(
        SubmissionService,
        service,
    )
    boundary = "stage7-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="essay.docx"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n"
        "\r\n"
        "test-content\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    with TestClient(application) as client:
        response = client.post(
            f"/assignments/{ASSIGNMENT_ID}/submissions",
            content=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(MAX_SUBMISSION_REQUEST_BYTES + 1),
            },
        )

    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "file_too_large"
    assert service.upload_calls == 0


def test_exact_file_size_submission_reaches_service() -> None:
    service = RecordingSubmissionService()
    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_submission_service] = lambda: cast(
        SubmissionService,
        service,
    )

    with TestClient(application) as client:
        response = client.post(
            f"/assignments/{ASSIGNMENT_ID}/submissions",
            files={
                "file": (
                    "essay.docx",
                    b"x" * MAX_SUBMISSION_FILE_BYTES,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 200, response.text
    assert service.upload_calls == 1
    assert service.received is not None
    assert len(service.received) == MAX_SUBMISSION_FILE_BYTES


def test_chunked_oversized_submission_never_reaches_service() -> None:
    service = RecordingSubmissionService()
    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = teacher_account
    application.dependency_overrides[get_submission_service] = lambda: cast(
        SubmissionService,
        service,
    )

    boundary = "stage7-boundary"
    preamble = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="essay.docx"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n"
        "\r\n"
    ).encode()

    def chunks() -> list[bytes]:
        return [
            preamble,
            b"x" * (MAX_SUBMISSION_REQUEST_BYTES - len(preamble)),
            b"x",
        ]

    with TestClient(application) as client:
        response = client.post(
            f"/assignments/{ASSIGNMENT_ID}/submissions",
            content=iter(chunks()),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Transfer-Encoding": "chunked",
            },
        )

    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "file_too_large"
    assert service.upload_calls == 0
