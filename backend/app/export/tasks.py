"""独立导出 Worker：冻结快照到不可覆盖私有 XLSX 对象。"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from app.export.models import ClaimedExport
from app.export.worker_repository import SqlAlchemyExportWorkerRepository
from app.export.xlsx import (
    XLSX_MEDIA_TYPE,
    WorkbookValidationError,
    build_export_workbook,
    workbook_snapshot_from_frozen,
)
from app.storage.supabase import SupabaseObjectStorage, SupabaseStorageError


class ExportRetryRequired(RuntimeError):
    """已有 Worker 持有租约，消息必须延迟到租约到期后再领取。"""

    def __init__(self, countdown_seconds: int) -> None:
        super().__init__("export_lease_active")
        self.countdown_seconds = countdown_seconds


class ExportRunner:
    def __init__(
        self,
        *,
        repository: SqlAlchemyExportWorkerRepository,
        storage: SupabaseObjectStorage,
    ) -> None:
        self._repository = repository
        self._storage = storage

    async def _claim(self, export_id: UUID) -> tuple[ClaimedExport, UUID] | None:
        lease_token = uuid4()
        claimed = await self._repository.claim(export_id, lease_token)
        if claimed is None:
            countdown_seconds = await self._repository.claim_retry_delay_seconds(export_id)
            if countdown_seconds is not None:
                raise ExportRetryRequired(countdown_seconds)
            return None
        return claimed, lease_token

    async def fail_timed_out(self, export_id: UUID) -> str:
        claim = await self._claim(export_id)
        if claim is None:
            return "not_claimed"
        _, lease_token = claim
        failed = await self._repository.fail(
            export_id,
            lease_token,
            "export_workbook_timeout",
        )
        return "export_workbook_timeout" if failed else "lease_lost"

    async def run(self, export_id: UUID) -> str:
        claim = await self._claim(export_id)
        if claim is None:
            return "not_claimed"
        claimed, lease_token = claim
        frozen = claimed.export
        object_key = f"exports/{export_id}/workbook.xlsx"
        created_object = False
        try:
            workbook_snapshot = workbook_snapshot_from_frozen(
                frozen.id,
                frozen.export_type,
                frozen.workbook_schema_version,
                frozen.snapshot_at,
                frozen.batch_snapshot,
                frozen.items,
            )
            artifact = await asyncio.to_thread(
                build_export_workbook,
                workbook_snapshot,
                now=frozen.generation_started_at,
            )
            with TemporaryDirectory(prefix="paper-grading-export-") as temporary_directory:
                path = Path(temporary_directory) / "workbook.xlsx"
                await asyncio.to_thread(path.write_bytes, artifact.content)
                created_object = await self._storage.put_file_once(
                    object_key,
                    path,
                    media_type=XLSX_MEDIA_TYPE,
                    content_sha256=artifact.file_sha256,
                )
            completed = await self._repository.complete(
                export_id,
                lease_token,
                object_key=object_key,
                safe_filename=artifact.safe_filename,
                file_size_bytes=artifact.file_size_bytes,
                file_sha256=artifact.file_sha256,
            )
            if completed:
                return "completed"
            cleanup_allowed = await self._repository.fail(
                export_id,
                lease_token,
                "export_completion_failed",
            )
            if created_object and cleanup_allowed:
                try:
                    await self._storage.delete_if_sha256(object_key, artifact.file_sha256)
                except SupabaseStorageError as error:
                    raise RuntimeError("export_cleanup_failed") from error
            return "export_completion_failed" if cleanup_allowed else "lease_lost"
        except WorkbookValidationError as error:
            await self._repository.fail(export_id, lease_token, error.code)
            return error.code
        except SupabaseStorageError:
            await self._repository.fail(export_id, lease_token, "export_storage_failed")
            return "export_storage_failed"
        except (OSError, UnicodeError):
            await self._repository.fail(export_id, lease_token, "export_workbook_failed")
            return "export_workbook_failed"
