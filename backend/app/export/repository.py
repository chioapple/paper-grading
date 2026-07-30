"""阶段十二导出的 RLS 仓储与原子创建入口。"""

import json
from collections import defaultdict
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.export.models import (
    ExportCreateInput,
    ExportCreation,
    ExportStatus,
    ExportType,
    ExportView,
)
from app.export.service import ExportDataError, ExportIdempotencyConflict, ExportNotFoundError

_STABLE_CREATE_ERRORS = {
    "export_job_not_ready": "评分批次尚不能导出",
    "export_source_missing": "批次存在没有可复核结果的论文",
    "export_final_unconfirmed": "最终导出要求全部论文已经教师确认",
    "export_snapshot_invalid": "导出快照无效",
}


class SqlAlchemyExportRepository:
    """教师只能查询；创建和冻结全部通过 0017 私有函数。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    async def _assume_teacher_role(session: AsyncSession, owner_id: UUID) -> None:
        claims = json.dumps(
            {"sub": str(owner_id), "role": "authenticated"},
            separators=(",", ":"),
        )
        await session.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": claims},
        )
        await session.execute(text("set local role paper_grading_teacher_api"))

    @asynccontextmanager
    async def _teacher_session(self, owner_id: UUID) -> AsyncIterator[AsyncSession]:
        async with self._database.sessions() as session, session.begin():
            await self._assume_teacher_role(session, owner_id)
            yield session

    @staticmethod
    def _raise_create_error(error: DBAPIError) -> None:
        message = str(error.orig)
        if "export_idempotency_conflict" in message:
            raise ExportIdempotencyConflict from error
        if "export_job_not_found" in message:
            raise ExportNotFoundError from error
        for code, safe_message in _STABLE_CREATE_ERRORS.items():
            if code in message:
                raise ExportDataError(code, safe_message) from error
        raise error

    @staticmethod
    def _view(
        row: Mapping[str, object],
        source_counts: Mapping[str, int],
    ) -> ExportView:
        metadata = row.get("audit_metadata")
        if not isinstance(metadata, dict):
            raise ExportDataError("export_snapshot_invalid", "导出快照无效")
        title = metadata.get("assignment_title")
        paper_count = metadata.get("paper_count")
        if not isinstance(title, str) or not isinstance(paper_count, int):
            raise ExportDataError("export_snapshot_invalid", "导出快照无效")
        return ExportView(
            id=cast(UUID, row["id"]),
            assignment_id=cast(UUID, row["assignment_id"]),
            grading_job_id=cast(UUID, row["grading_job_id"]),
            assignment_title=title,
            export_type=cast(ExportType, row["export_type"]),
            status=cast(ExportStatus, row["status"]),
            paper_count=paper_count,
            source_counts=dict(source_counts),
            safe_filename=cast(str | None, row.get("safe_filename")),
            error_code=cast(str | None, row.get("error_code")),
            snapshot_at=cast(datetime, row["snapshot_at"]),
            started_at=cast(datetime | None, row.get("started_at")),
            finished_at=cast(datetime | None, row.get("finished_at")),
            created_at=cast(datetime, row["created_at"]),
        )

    @staticmethod
    async def _source_counts(
        session: AsyncSession,
        export_ids: tuple[UUID, ...],
    ) -> dict[UUID, dict[str, int]]:
        if not export_ids:
            return {}
        rows = (
            await session.execute(
                text(
                    "select export_id, source_type, count(*) as item_count "
                    "from public.export_items where export_id = any(cast(:export_ids as uuid[])) "
                    "group by export_id, source_type"
                ),
                {"export_ids": list(export_ids)},
            )
        ).mappings()
        result: dict[UUID, dict[str, int]] = defaultdict(dict)
        for row in rows:
            result[cast(UUID, row["export_id"])][cast(str, row["source_type"])] = cast(
                int, row["item_count"]
            )
        return result

    async def create(
        self,
        owner_id: UUID,
        request: ExportCreateInput,
        idempotency_key: str,
    ) -> ExportCreation:
        request_hash = request.request_hash()
        async with self._teacher_session(owner_id) as session:
            existing = (
                (
                    await session.execute(
                        text(
                            "select * from public.exports "
                            "where owner_id = :owner_id and idempotency_key = :idempotency_key"
                        ),
                        {"owner_id": owner_id, "idempotency_key": idempotency_key},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                existing is not None
                and bytes(cast(bytes, existing["request_hash"])) != request_hash
            ):
                raise ExportIdempotencyConflict
            created = existing is None
            if created:
                try:
                    await session.execute(
                        text(
                            "select * from paper_grading_private.create_export("
                            ":job_id, :export_type, :idempotency_key, :request_hash)"
                        ),
                        {
                            "job_id": request.grading_job_id,
                            "export_type": request.export_type,
                            "idempotency_key": idempotency_key,
                            "request_hash": request_hash,
                        },
                    )
                except DBAPIError as error:
                    self._raise_create_error(error)
                existing = (
                    (
                        await session.execute(
                            text(
                                "select * from public.exports "
                                "where owner_id = :owner_id and idempotency_key = :idempotency_key"
                            ),
                            {"owner_id": owner_id, "idempotency_key": idempotency_key},
                        )
                    )
                    .mappings()
                    .one()
                )
            assert existing is not None
            export_id = cast(UUID, existing["id"])
            counts = await self._source_counts(session, (export_id,))
            return ExportCreation(
                export=self._view(
                    cast(Mapping[str, object], existing),
                    counts.get(export_id, {}),
                ),
                created=created,
            )

    async def list(self, owner_id: UUID) -> tuple[ExportView, ...]:
        async with self._teacher_session(owner_id) as session:
            rows = tuple(
                (
                    await session.execute(
                        text(
                            "select * from public.exports where owner_id = :owner_id "
                            "order by created_at desc, id limit 100"
                        ),
                        {"owner_id": owner_id},
                    )
                ).mappings()
            )
            counts = await self._source_counts(
                session,
                tuple(cast(UUID, row["id"]) for row in rows),
            )
            return tuple(
                self._view(
                    cast(Mapping[str, object], row),
                    counts.get(cast(UUID, row["id"]), {}),
                )
                for row in rows
            )

    async def get(self, owner_id: UUID, export_id: UUID) -> ExportView | None:
        async with self._teacher_session(owner_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "select * from public.exports "
                            "where owner_id = :owner_id and id = :export_id"
                        ),
                        {"owner_id": owner_id, "export_id": export_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            counts = await self._source_counts(session, (export_id,))
            return self._view(cast(Mapping[str, object], row), counts.get(export_id, {}))

    async def get_object_key(self, owner_id: UUID, export_id: UUID) -> str | None:
        async with self._teacher_session(owner_id) as session:
            value = await session.scalar(
                text(
                    "select object_key from public.exports "
                    "where owner_id = :owner_id and id = :export_id and status = 'completed'"
                ),
                {"owner_id": owner_id, "export_id": export_id},
            )
            return cast(str | None, value)
