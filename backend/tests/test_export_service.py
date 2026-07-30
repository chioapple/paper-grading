"""阶段十二导出服务的公共行为。"""

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError

from app.export.models import ExportCreateInput, ExportCreation, ExportStatus, ExportView
from app.export.repository import SqlAlchemyExportRepository
from app.export.service import (
    ExportDataError,
    ExportDownloadStorage,
    ExportNotFoundError,
    ExportQueue,
    ExportRepository,
    ExportService,
    ExportStateError,
)

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
EXPORT_ID = UUID("33333333-3333-4333-8333-333333333333")
ASSIGNMENT_ID = UUID("44444444-4444-4444-8444-444444444444")


def export_view(status: str = "queued") -> ExportView:
    now = datetime(2026, 7, 22, tzinfo=UTC)
    return ExportView(
        id=EXPORT_ID,
        assignment_id=ASSIGNMENT_ID,
        grading_job_id=JOB_ID,
        assignment_title="Argumentative essay",
        export_type="draft",
        status=cast(ExportStatus, status),
        paper_count=2,
        source_counts={"ai_suggestion": 2},
        safe_filename="grades.xlsx" if status == "completed" else None,
        error_code=None,
        snapshot_at=now,
        started_at=None,
        finished_at=now if status == "completed" else None,
        created_at=now,
    )


def test_same_queued_export_is_reenqueued_without_creating_another() -> None:
    class Repository:
        async def create(self, *_args: object) -> ExportCreation:
            return ExportCreation(export=export_view(), created=False)

    queued: list[UUID] = []

    class Queue:
        async def enqueue(self, export_id: UUID) -> None:
            queued.append(export_id)

    service = ExportService(
        repository=cast(ExportRepository, Repository()),
        queue=cast(ExportQueue, Queue()),
        storage=cast(ExportDownloadStorage, object()),
        signed_url_ttl_seconds=60,
    )
    result = asyncio.run(
        service.create(
            OWNER_ID,
            ExportCreateInput(grading_job_id=JOB_ID, export_type="draft"),
            "same-click-key",
        )
    )

    assert result.created is False
    assert queued == [EXPORT_ID]


def test_invalid_idempotency_key_fails_before_repository() -> None:
    service = ExportService(
        repository=cast(ExportRepository, object()),
        queue=cast(ExportQueue, object()),
        storage=cast(ExportDownloadStorage, object()),
        signed_url_ttl_seconds=60,
    )
    with pytest.raises(ExportDataError, match="幂等键无效"):
        asyncio.run(
            service.create(
                OWNER_ID,
                ExportCreateInput(grading_job_id=JOB_ID, export_type="draft"),
                "   ",
            )
        )


def test_repository_hides_missing_and_cross_teacher_jobs_as_not_found() -> None:
    error = DBAPIError("select create_export", {}, Exception("export_job_not_found"))

    with pytest.raises(ExportNotFoundError):
        SqlAlchemyExportRepository._raise_create_error(error)


def test_download_requires_completed_export_and_returns_safe_filename() -> None:
    class Repository:
        async def get(self, *_args: object) -> ExportView:
            return export_view("completed")

        async def get_object_key(self, *_args: object) -> str:
            return f"exports/{EXPORT_ID}/workbook.xlsx"

    class Storage:
        async def create_download_url(self, _key: str) -> str:
            return "https://storage.example.test/signed"

    service = ExportService(
        repository=cast(ExportRepository, Repository()),
        queue=cast(ExportQueue, object()),
        storage=cast(ExportDownloadStorage, Storage()),
        signed_url_ttl_seconds=60,
    )
    result = asyncio.run(service.download(OWNER_ID, EXPORT_ID))
    assert result.filename == "grades.xlsx"
    assert result.expires_in_seconds == 60


def test_download_rejects_queued_export() -> None:
    class Repository:
        async def get(self, *_args: object) -> ExportView:
            return export_view()

    service = ExportService(
        repository=cast(ExportRepository, Repository()),
        queue=cast(ExportQueue, object()),
        storage=cast(ExportDownloadStorage, object()),
        signed_url_ttl_seconds=60,
    )
    with pytest.raises(ExportStateError):
        asyncio.run(service.download(OWNER_ID, EXPORT_ID))
