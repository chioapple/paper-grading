"""论文元数据的 PostgreSQL 持久化实现。"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.domain.models import Assignment, Submission
from app.submissions.models import (
    SubmissionReservation,
    SubmissionReservationRequest,
    SubmissionView,
)


class SqlAlchemySubmissionRepository:
    """所有教师操作都在短事务内写入 RLS 身份。"""

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
    def _to_view(row: Submission) -> SubmissionView:
        return SubmissionView(
            id=row.id,
            assignment_id=row.assignment_id,
            original_filename=row.original_filename,
            media_type=row.media_type,
            file_size_bytes=row.file_size_bytes,
            status=row.status,
            error_code=row.error_code,
            created_at=row.created_at,
        )

    async def reserve_submission(
        self,
        owner_id: UUID,
        request: SubmissionReservationRequest,
    ) -> SubmissionReservation:
        """锁定作业后原子插入；哈希冲突返回已有论文。"""

        async with self._teacher_session(owner_id) as session:
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == request.assignment_id,
                    Assignment.owner_id == owner_id,
                )
                .with_for_update()
            )
            if assignment is None:
                return SubmissionReservation(state="assignment_not_found", submission=None)
            if assignment.status != "ready":
                return SubmissionReservation(state="assignment_not_ready", submission=None)

            statement = (
                insert(Submission)
                .values(
                    id=request.id,
                    owner_id=owner_id,
                    assignment_id=request.assignment_id,
                    original_filename=request.original_filename,
                    media_type=request.media_type,
                    file_size_bytes=request.file_size_bytes,
                    content_sha256=request.content_sha256,
                    source_object_key=request.source_object_key,
                    extracted_object_key=None,
                    status="uploaded",
                    error_code=None,
                )
                .on_conflict_do_nothing(
                    index_elements=["assignment_id", "content_sha256"],
                )
                .returning(Submission)
            )
            created = (await session.execute(statement)).scalar_one_or_none()
            if created is not None:
                return SubmissionReservation(
                    state="created",
                    submission=self._to_view(created),
                )
            existing = await session.scalar(
                select(Submission).where(
                    Submission.assignment_id == request.assignment_id,
                    Submission.owner_id == owner_id,
                    Submission.content_sha256 == request.content_sha256,
                )
            )
            if existing is None:
                raise RuntimeError("论文哈希冲突后未找到已有记录")
            return SubmissionReservation(
                state="duplicate",
                submission=self._to_view(existing),
            )

    async def transition_submission(
        self,
        owner_id: UUID,
        submission_id: UUID,
        *,
        status: str,
        extracted_object_key: str | None = None,
        error_code: str | None = None,
    ) -> SubmissionView | None:
        """调用阶段七受限函数，不授予教师表级 UPDATE。"""

        async with self._teacher_session(owner_id) as session:
            transitioned_id = cast(
                UUID | None,
                await session.scalar(
                    text(
                        "select paper_grading_private.transition_submission("
                        "cast(:submission_id as uuid), :status, :extracted_key, :error_code)"
                    ),
                    {
                        "submission_id": submission_id,
                        "status": status,
                        "extracted_key": extracted_object_key,
                        "error_code": error_code,
                    },
                ),
            )
            if transitioned_id is None:
                return None
            row = await session.scalar(
                select(Submission).where(
                    Submission.id == transitioned_id,
                    Submission.owner_id == owner_id,
                )
            )
            return self._to_view(row) if row is not None else None

    async def list_submissions(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> list[SubmissionView] | None:
        async with self._teacher_session(owner_id) as session:
            assignment_exists = await session.scalar(
                select(Assignment.id).where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                )
            )
            if assignment_exists is None:
                return None
            rows = list(
                (
                    await session.scalars(
                        select(Submission)
                        .where(
                            Submission.assignment_id == assignment_id,
                            Submission.owner_id == owner_id,
                        )
                        .order_by(Submission.created_at.desc(), Submission.id.desc())
                    )
                ).all()
            )
            return [self._to_view(row) for row in rows]

    async def get_ready_source_key(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        submission_id: UUID,
    ) -> str | None:
        async with self._teacher_session(owner_id) as session:
            return cast(
                str | None,
                await session.scalar(
                    select(Submission.source_object_key).where(
                        Submission.id == submission_id,
                        Submission.assignment_id == assignment_id,
                        Submission.owner_id == owner_id,
                        Submission.status == "ready",
                    )
                ),
            )
