"""阶段七论文上传服务测试。"""

import asyncio
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from docx import Document
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.monitoring.repository import QuotaExceededError
from app.parsing.models import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE, DocumentParseError, ParseLimits
from app.storage.supabase import SupabaseStorageError
from app.submissions.models import (
    IncomingSubmission,
    SubmissionReservation,
    SubmissionReservationRequest,
    SubmissionView,
)
from app.submissions.service import SubmissionService, SubmissionTransitionError

OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
ASSIGNMENT_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("77777777-7777-7777-7777-777777777777")


def build_docx() -> bytes:
    output = BytesIO()
    document = Document()
    document.add_paragraph("A clear thesis statement.")
    document.save(output)
    return output.getvalue()


def build_scanned_pdf() -> bytes:
    image_output = BytesIO()
    Image.new("RGB", (20, 20), "black").save(image_output, format="PNG")
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    document.drawImage(ImageReader(BytesIO(image_output.getvalue())), 72, 700, 200, 100)
    document.save()
    return output.getvalue()


class InMemorySubmissionRepository:
    def __init__(self) -> None:
        self.submission: SubmissionView | None = None
        self.transitions: list[str] = []

    async def reserve_submission(
        self,
        owner_id: UUID,
        request: SubmissionReservationRequest,
    ) -> SubmissionReservation:
        assert owner_id == OWNER_ID
        self.submission = SubmissionView(
            id=request.id,
            assignment_id=request.assignment_id,
            original_filename=request.original_filename,
            media_type=request.media_type,
            file_size_bytes=request.file_size_bytes,
            status="uploaded",
            error_code=None,
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        return SubmissionReservation(state="created", submission=self.submission)

    async def transition_submission(
        self,
        owner_id: UUID,
        submission_id: UUID,
        *,
        status: str,
        extracted_object_key: str | None = None,
        error_code: str | None = None,
    ) -> SubmissionView | None:
        assert owner_id == OWNER_ID
        assert submission_id == SUBMISSION_ID
        assert self.submission is not None
        self.transitions.append(status)
        self.submission = self.submission.model_copy(
            update={"status": status, "error_code": error_code}
        )
        return self.submission

    async def list_submissions(self, owner_id: UUID, assignment_id: UUID) -> list[SubmissionView]:
        raise AssertionError("本测试不读取列表")

    async def get_ready_source_key(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        submission_id: UUID,
    ) -> str | None:
        raise AssertionError("本测试不生成下载地址")


class MemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put_file(
        self,
        key: str,
        path: Path,
        *,
        media_type: str,
        content_sha256: bytes,
    ) -> None:
        assert media_type in {DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE}
        assert len(content_sha256) == 32
        self.objects[key] = path.read_bytes()

    async def put_json(self, key: str, content: bytes) -> None:
        self.objects[key] = content

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def create_download_url(self, key: str) -> str:
        raise AssertionError("本测试不生成下载地址")


def test_valid_docx_is_stored_parsed_and_marked_ready(tmp_path: Path) -> None:
    repository = InMemorySubmissionRepository()
    storage = MemoryObjectStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        parse_limits=ParseLimits(),
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    result = asyncio.run(
        service.upload_submission(
            OWNER_ID,
            ASSIGNMENT_ID,
            IncomingSubmission(
                stream=BytesIO(build_docx()),
                original_filename="essay.docx",
                client_media_type=DOCX_MEDIA_TYPE,
            ),
        )
    )

    assert result.duplicate is False
    assert result.submission.status == "ready"
    assert repository.transitions == ["parsing", "ready"]
    assert len(storage.objects) == 2
    parsed_object = next(
        content
        for key, content in storage.objects.items()
        if key.endswith("document-blocks.v1.json")
    )
    assert json.loads(parsed_object)["blocks"][0]["text"] == "A clear thesis statement."
    assert list(tmp_path.iterdir()) == []


def test_parser_rejection_marks_submission_failed_with_stable_code(tmp_path: Path) -> None:
    repository = InMemorySubmissionRepository()
    storage = MemoryObjectStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    with pytest.raises(DocumentParseError) as error:
        asyncio.run(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_scanned_pdf()),
                    original_filename="scan.pdf",
                    client_media_type=PDF_MEDIA_TYPE,
                ),
            )
        )

    assert error.value.code == "pdf_scan_unsupported"
    assert repository.transitions == ["parsing", "failed"]
    assert repository.submission is not None
    assert repository.submission.error_code == "pdf_scan_unsupported"
    assert len(storage.objects) == 1
    assert list(tmp_path.iterdir()) == []


def test_storage_quota_block_marks_the_reserved_submission_retryable(
    tmp_path: Path,
) -> None:
    class QuotaBlockedStorage(MemoryObjectStorage):
        async def put_file(
            self,
            key: str,
            path: Path,
            *,
            media_type: str,
            content_sha256: bytes,
        ) -> None:
            raise QuotaExceededError(
                resource="storage",
                code="storage_quota_exceeded",
            )

    repository = InMemorySubmissionRepository()
    service = SubmissionService(
        repository=repository,
        storage=QuotaBlockedStorage(),
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    with pytest.raises(QuotaExceededError, match="storage_quota_exceeded"):
        asyncio.run(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_docx()),
                    original_filename="quota-blocked.docx",
                    client_media_type=DOCX_MEDIA_TYPE,
                ),
            )
        )

    assert repository.transitions == ["failed"]
    assert repository.submission is not None
    assert repository.submission.error_code == "storage_quota_exceeded"


def test_ready_duplicate_returns_existing_submission_without_rewriting_objects(
    tmp_path: Path,
) -> None:
    class DuplicateRepository(InMemorySubmissionRepository):
        async def reserve_submission(
            self,
            owner_id: UUID,
            request: SubmissionReservationRequest,
        ) -> SubmissionReservation:
            reservation = await super().reserve_submission(owner_id, request)
            assert reservation.submission is not None
            self.submission = reservation.submission.model_copy(update={"status": "ready"})
            return SubmissionReservation(state="duplicate", submission=self.submission)

    repository = DuplicateRepository()
    storage = MemoryObjectStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    result = asyncio.run(
        service.upload_submission(
            OWNER_ID,
            ASSIGNMENT_ID,
            IncomingSubmission(
                stream=BytesIO(build_docx()),
                original_filename="duplicate.docx",
                client_media_type=DOCX_MEDIA_TYPE,
            ),
        )
    )

    assert result.duplicate is True
    assert result.submission.status == "ready"
    assert storage.objects == {}
    assert repository.transitions == []


def test_failed_duplicate_is_reset_and_reprocessed(tmp_path: Path) -> None:
    class FailedDuplicateRepository(InMemorySubmissionRepository):
        async def reserve_submission(
            self,
            owner_id: UUID,
            request: SubmissionReservationRequest,
        ) -> SubmissionReservation:
            reservation = await super().reserve_submission(owner_id, request)
            assert reservation.submission is not None
            self.submission = reservation.submission.model_copy(
                update={"status": "failed", "error_code": "pdf_scan_unsupported"}
            )
            return SubmissionReservation(state="duplicate", submission=self.submission)

    repository = FailedDuplicateRepository()
    storage = MemoryObjectStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    result = asyncio.run(
        service.upload_submission(
            OWNER_ID,
            ASSIGNMENT_ID,
            IncomingSubmission(
                stream=BytesIO(build_docx()),
                original_filename="retry.docx",
                client_media_type=DOCX_MEDIA_TYPE,
            ),
        )
    )

    assert result.duplicate is False
    assert result.submission.status == "ready"
    assert repository.transitions == ["uploaded", "parsing", "ready"]
    assert len(storage.objects) == 2


def test_unreferenced_extracted_object_is_deleted_when_ready_transition_fails(
    tmp_path: Path,
) -> None:
    class ReadyTransitionFailsRepository(InMemorySubmissionRepository):
        async def transition_submission(
            self,
            owner_id: UUID,
            submission_id: UUID,
            *,
            status: str,
            extracted_object_key: str | None = None,
            error_code: str | None = None,
        ) -> SubmissionView | None:
            if status == "ready":
                return None
            return await super().transition_submission(
                owner_id,
                submission_id,
                status=status,
                extracted_object_key=extracted_object_key,
                error_code=error_code,
            )

    repository = ReadyTransitionFailsRepository()
    storage = MemoryObjectStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    with pytest.raises(SubmissionTransitionError):
        asyncio.run(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_docx()),
                    original_filename="essay.docx",
                    client_media_type=DOCX_MEDIA_TYPE,
                ),
            )
        )

    assert len(storage.objects) == 1
    assert len(storage.deleted) == 1
    assert storage.deleted[0].endswith("/document-blocks.v1.json")


def test_cleanup_failure_preserves_the_original_transition_error(tmp_path: Path) -> None:
    class ReadyTransitionFailsRepository(InMemorySubmissionRepository):
        async def transition_submission(
            self,
            owner_id: UUID,
            submission_id: UUID,
            *,
            status: str,
            extracted_object_key: str | None = None,
            error_code: str | None = None,
        ) -> SubmissionView | None:
            if status == "ready":
                return None
            return await super().transition_submission(
                owner_id,
                submission_id,
                status=status,
                extracted_object_key=extracted_object_key,
                error_code=error_code,
            )

    class DeleteFailsStorage(MemoryObjectStorage):
        async def delete(self, key: str) -> None:
            await super().delete(key)
            raise SupabaseStorageError("模拟补偿删除失败")

    service = SubmissionService(
        repository=ReadyTransitionFailsRepository(),
        storage=DeleteFailsStorage(),
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    with pytest.raises(SubmissionTransitionError) as error:
        asyncio.run(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_docx()),
                    original_filename="essay.docx",
                    client_media_type=DOCX_MEDIA_TYPE,
                ),
            )
        )

    assert isinstance(error.value.__cause__, SupabaseStorageError)
    assert str(error.value.__cause__) == "模拟补偿删除失败"


def test_possibly_written_extracted_object_is_deleted_when_write_reports_failure(
    tmp_path: Path,
) -> None:
    class AmbiguousWriteStorage(MemoryObjectStorage):
        async def put_json(self, key: str, content: bytes) -> None:
            await super().put_json(key, content)
            raise SupabaseStorageError("模拟服务端写入后客户端超时")

    repository = InMemorySubmissionRepository()
    storage = AmbiguousWriteStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    with pytest.raises(SupabaseStorageError):
        asyncio.run(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_docx()),
                    original_filename="essay.docx",
                    client_media_type=DOCX_MEDIA_TYPE,
                ),
            )
        )

    assert repository.transitions == ["parsing", "failed"]
    assert len(storage.objects) == 1
    assert len(storage.deleted) == 1
    assert storage.deleted[0].endswith("/document-blocks.v1.json")


def test_unreferenced_extracted_object_is_deleted_when_ready_transition_is_cancelled(
    tmp_path: Path,
) -> None:
    class ReadyTransitionCancelledRepository(InMemorySubmissionRepository):
        async def transition_submission(
            self,
            owner_id: UUID,
            submission_id: UUID,
            *,
            status: str,
            extracted_object_key: str | None = None,
            error_code: str | None = None,
        ) -> SubmissionView | None:
            if status == "ready":
                raise asyncio.CancelledError
            return await super().transition_submission(
                owner_id,
                submission_id,
                status=status,
                extracted_object_key=extracted_object_key,
                error_code=error_code,
            )

    repository = ReadyTransitionCancelledRepository()
    storage = MemoryObjectStorage()
    service = SubmissionService(
        repository=repository,
        storage=storage,
        temporary_root=tmp_path,
        id_factory=lambda: SUBMISSION_ID,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_docx()),
                    original_filename="essay.docx",
                    client_media_type=DOCX_MEDIA_TYPE,
                ),
            )
        )

    assert len(storage.objects) == 1
    assert len(storage.deleted) == 1
    assert storage.deleted[0].endswith("/document-blocks.v1.json")
    assert repository.transitions == ["parsing", "failed"]
    assert repository.submission is not None
    assert repository.submission.error_code == "processing_cancelled"


def test_cancelled_extracted_write_finishes_before_compensating_delete(tmp_path: Path) -> None:
    async def scenario() -> tuple[MemoryObjectStorage, InMemorySubmissionRepository]:
        class DelayedWriteStorage(MemoryObjectStorage):
            def __init__(self) -> None:
                super().__init__()
                self.write_started = asyncio.Event()
                self.release_write = asyncio.Event()

            async def put_json(self, key: str, content: bytes) -> None:
                self.write_started.set()
                await self.release_write.wait()
                await super().put_json(key, content)

        repository = InMemorySubmissionRepository()
        storage = DelayedWriteStorage()
        service = SubmissionService(
            repository=repository,
            storage=storage,
            temporary_root=tmp_path,
            id_factory=lambda: SUBMISSION_ID,
        )
        task = asyncio.create_task(
            service.upload_submission(
                OWNER_ID,
                ASSIGNMENT_ID,
                IncomingSubmission(
                    stream=BytesIO(build_docx()),
                    original_filename="essay.docx",
                    client_media_type=DOCX_MEDIA_TYPE,
                ),
            )
        )
        await storage.write_started.wait()
        task.cancel()
        storage.release_write.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        return storage, repository

    storage, repository = asyncio.run(scenario())

    assert len(storage.objects) == 1
    assert len(storage.deleted) == 1
    assert storage.deleted[0].endswith("/document-blocks.v1.json")
    assert repository.transitions == ["parsing", "failed"]
    assert repository.submission is not None
    assert repository.submission.error_code == "processing_cancelled"
