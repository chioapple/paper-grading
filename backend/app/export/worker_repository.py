"""独立导出 Worker 的最小数据库能力。"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.export.models import ClaimedExport, ExportType, FrozenExport

EXPORT_LEASE_SECONDS = 600


class SqlAlchemyExportWorkerRepository:
    """只领取、读取冻结快照并结束导出，不读取评分实时表。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    @asynccontextmanager
    async def _worker_session(self) -> AsyncIterator[AsyncSession]:
        async with self._database.sessions() as session, session.begin():
            await session.execute(text("set local role paper_grading_export_worker"))
            yield session

    @staticmethod
    def _frozen(row: Mapping[str, object], items: tuple[dict[str, object], ...]) -> FrozenExport:
        metadata = row.get("audit_metadata")
        if not isinstance(metadata, dict):
            raise ValueError("export_snapshot_invalid")
        metadata = {
            **metadata,
            "assignment_id": str(row["assignment_id"]),
            "grading_job_id": str(row["grading_job_id"]),
        }
        return FrozenExport(
            id=cast(UUID, row["id"]),
            export_type=cast(ExportType, row["export_type"]),
            workbook_schema_version=cast(str, row["workbook_schema_version"]),
            snapshot_at=cast(datetime, row["snapshot_at"]),
            generation_started_at=cast(datetime, row["started_at"]),
            batch_snapshot=metadata,
            items=items,
        )

    async def claim(
        self,
        export_id: UUID,
        lease_token: UUID,
        *,
        lease_seconds: int = EXPORT_LEASE_SECONDS,
    ) -> ClaimedExport | None:
        async with self._worker_session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "select * from paper_grading_private.claim_export("
                            ":export_id, :lease_token, :lease_seconds)"
                        ),
                        {
                            "export_id": export_id,
                            "lease_token": lease_token,
                            "lease_seconds": lease_seconds,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row.get("claim_token") != lease_token:
                return None
            item_rows = tuple(
                dict(item)
                for item in (
                    await session.execute(
                        text(
                            "select id, export_id, grading_job_item_id, submission_id, "
                            "grading_attempt_id, teacher_review_id, review_revision, position, "
                            "source_type, original_filename, result_snapshot "
                            "from public.export_items where export_id = :export_id "
                            "order by position"
                        ),
                        {"export_id": export_id},
                    )
                ).mappings()
            )
            return ClaimedExport(
                export=self._frozen(cast(Mapping[str, object], row), item_rows),
                lease_token=lease_token,
            )

    async def claim_retry_delay_seconds(self, export_id: UUID) -> int | None:
        """仅对仍可执行的任务返回下一次安全领取的等待秒数。"""

        async with self._worker_session() as session:
            delay = await session.scalar(
                text(
                    "select case "
                    "when status = 'queued' then 1 "
                    "when status = 'running' then greatest(1, ceil(extract(epoch from "
                    "(lease_expires_at - transaction_timestamp()))))::integer "
                    "else null end "
                    "from public.exports where id = :export_id "
                    "and status in ('queued', 'running')"
                ),
                {"export_id": export_id},
            )
            return cast(int | None, delay)

    async def complete(
        self,
        export_id: UUID,
        lease_token: UUID,
        *,
        object_key: str,
        safe_filename: str,
        file_size_bytes: int,
        file_sha256: bytes,
    ) -> bool:
        async with self._worker_session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "select * from paper_grading_private.complete_export("
                            ":export_id, :lease_token, :object_key, :safe_filename, "
                            ":file_size_bytes, :file_sha256)"
                        ),
                        {
                            "export_id": export_id,
                            "lease_token": lease_token,
                            "object_key": object_key,
                            "safe_filename": safe_filename,
                            "file_size_bytes": file_size_bytes,
                            "file_sha256": file_sha256,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            return row is not None and row.get("status") == "completed"

    async def fail(self, export_id: UUID, lease_token: UUID, error_code: str) -> bool:
        async with self._worker_session() as session:
            row = (
                (
                    await session.execute(
                        text(
                            "select * from paper_grading_private.fail_export("
                            ":export_id, :lease_token, :error_code)"
                        ),
                        {
                            "export_id": export_id,
                            "lease_token": lease_token,
                            "error_code": error_code,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            return row is not None and row.get("status") == "failed"
