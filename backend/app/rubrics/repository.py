"""作业与 Rubric 的 PostgreSQL 持久化实现。"""

import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.domain.models import Assignment, ProviderConfig, RubricVersion
from app.domain.rubric import StructuredRubric
from app.providers.config import StoredProviderConfig
from app.rubrics.models import (
    AssignmentCreate,
    AssignmentDetail,
    AssignmentSummary,
    AssignmentUpdate,
    RubricDraftCreate,
    RubricPointer,
    RubricView,
)


class SqlAlchemyAssignmentRubricRepository:
    """用短事务执行教师 RLS 操作，并单独读取受保护供应商配置。"""

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
    def _to_rubric(row: RubricVersion) -> RubricView:
        structured = (
            StructuredRubric.model_validate(row.structured_rubric)
            if row.structured_rubric is not None
            else None
        )
        return RubricView.model_validate(
            {
                "id": row.id,
                "assignment_id": row.assignment_id,
                "version": row.version,
                "status": row.status,
                "original_rubric": row.original_rubric,
                "structured_rubric": structured,
                "total_score": row.total_score,
                "score_step": row.score_step,
                "provider_config_id": row.provider_config_id,
                "model": row.model,
                "confirmed_at": row.confirmed_at,
                "created_at": row.created_at,
            }
        )

    @classmethod
    def _to_summary(
        cls,
        row: Assignment,
        rubric_rows: list[RubricVersion],
    ) -> AssignmentSummary:
        rubrics = [cls._to_rubric(item) for item in rubric_rows]
        latest = rubrics[0] if rubrics else None
        draft = next((item for item in rubrics if item.status == "draft"), None)
        confirmed = next((item for item in rubrics if item.status == "confirmed"), None)
        return AssignmentSummary.model_validate(
            {
                "id": row.id,
                "title": row.title,
                "status": row.status,
                "current_rubric_status": latest.status if latest is not None else None,
                "current_rubric_version": latest.version if latest is not None else None,
                "current_draft_version": draft.version if draft is not None else None,
                "current_confirmed_version": (confirmed.version if confirmed is not None else None),
                "current_draft": (
                    RubricPointer(id=draft.id, version=draft.version, status=draft.status)
                    if draft is not None
                    else None
                ),
                "current_confirmed": (
                    RubricPointer(
                        id=confirmed.id,
                        version=confirmed.version,
                        status=confirmed.status,
                    )
                    if confirmed is not None
                    else None
                ),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    @classmethod
    def _to_detail(
        cls,
        row: Assignment,
        rubric_rows: list[RubricVersion],
    ) -> AssignmentDetail:
        summary = cls._to_summary(row, rubric_rows)
        return AssignmentDetail(
            **summary.model_dump(),
            instructions=row.instructions,
            rubric_versions=[cls._to_rubric(item) for item in rubric_rows],
        )

    @staticmethod
    async def _load_detail(
        session: AsyncSession,
        owner_id: UUID,
        assignment_id: UUID,
        *,
        lock_assignment: bool = False,
    ) -> AssignmentDetail | None:
        assignment_query = select(Assignment).where(
            Assignment.id == assignment_id,
            Assignment.owner_id == owner_id,
        )
        if lock_assignment:
            assignment_query = assignment_query.with_for_update()
        assignment = await session.scalar(assignment_query)
        if assignment is None:
            return None
        rubrics = list(
            (
                await session.scalars(
                    select(RubricVersion)
                    .where(
                        RubricVersion.assignment_id == assignment_id,
                        RubricVersion.owner_id == owner_id,
                    )
                    .order_by(RubricVersion.version.desc())
                )
            ).all()
        )
        return SqlAlchemyAssignmentRubricRepository._to_detail(assignment, rubrics)

    async def create_assignment(
        self,
        owner_id: UUID,
        payload: AssignmentCreate,
    ) -> AssignmentDetail:
        async with self._teacher_session(owner_id) as session:
            assignment = Assignment(
                owner_id=owner_id,
                title=payload.title,
                instructions=payload.instructions,
                status="draft",
            )
            session.add(assignment)
            await session.flush()
            rubric = RubricVersion(
                owner_id=owner_id,
                assignment_id=assignment.id,
                version=1,
                status="draft",
                original_rubric=payload.original_rubric,
                structured_rubric=None,
                total_score=payload.total_score,
                score_step=payload.score_step,
            )
            session.add(rubric)
            await session.flush()
            await session.refresh(assignment)
            await session.refresh(rubric)
            return self._to_detail(assignment, [rubric])

    async def list_assignments(self, owner_id: UUID) -> list[AssignmentSummary]:
        async with self._teacher_session(owner_id) as session:
            assignments = list(
                (
                    await session.scalars(
                        select(Assignment)
                        .where(Assignment.owner_id == owner_id)
                        .order_by(Assignment.created_at.desc(), Assignment.id.desc())
                    )
                ).all()
            )
            if not assignments:
                return []
            rubric_rows = list(
                (
                    await session.scalars(
                        select(RubricVersion)
                        .where(
                            RubricVersion.owner_id == owner_id,
                            RubricVersion.assignment_id.in_([item.id for item in assignments]),
                        )
                        .order_by(RubricVersion.version.desc())
                    )
                ).all()
            )
            grouped: dict[UUID, list[RubricVersion]] = defaultdict(list)
            for rubric in rubric_rows:
                grouped[rubric.assignment_id].append(rubric)
            return [self._to_summary(item, grouped[item.id]) for item in assignments]

    async def get_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> AssignmentDetail | None:
        async with self._teacher_session(owner_id) as session:
            return await self._load_detail(session, owner_id, assignment_id)

    async def update_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: AssignmentUpdate,
    ) -> AssignmentDetail | None:
        async with self._teacher_session(owner_id) as session:
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                    Assignment.status == "draft",
                )
                .with_for_update()
            )
            if assignment is None:
                return None
            assignment.title = payload.title
            assignment.instructions = payload.instructions
            assignment.updated_at = datetime.now(UTC)
            await session.flush()
            return await self._load_detail(session, owner_id, assignment_id)

    async def update_assignment_status(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        status: str,
    ) -> AssignmentDetail | None:
        async with self._teacher_session(owner_id) as session:
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                )
                .with_for_update()
            )
            if assignment is None:
                return None
            if status == "draft" and assignment.status not in {"draft", "archived"}:
                return None
            if status not in {"draft", "archived"}:
                return None
            assignment.status = status
            assignment.updated_at = datetime.now(UTC)
            await session.flush()
            return await self._load_detail(session, owner_id, assignment_id)

    async def create_rubric_draft(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: RubricDraftCreate,
    ) -> RubricView | None:
        async with self._teacher_session(owner_id) as session:
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                )
                .with_for_update()
            )
            if assignment is None or assignment.status == "archived":
                return None
            existing_draft = await session.scalar(
                select(RubricVersion.id).where(
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                    RubricVersion.status == "draft",
                )
            )
            if existing_draft is not None:
                return None
            latest_version = await session.scalar(
                select(func.max(RubricVersion.version)).where(
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                )
            )
            rubric = RubricVersion(
                owner_id=owner_id,
                assignment_id=assignment_id,
                version=(latest_version or 0) + 1,
                status="draft",
                original_rubric=payload.original_rubric,
                structured_rubric=None,
                total_score=payload.total_score,
                score_step=payload.score_step,
            )
            session.add(rubric)
            await session.flush()
            await session.refresh(rubric)
            return self._to_rubric(rubric)

    async def get_provider_for_generation(
        self,
        provider_id: UUID,
    ) -> StoredProviderConfig | None:
        async with self._database.sessions() as session:
            provider = await session.get(ProviderConfig, provider_id)
            if provider is None:
                return None
            return StoredProviderConfig.model_validate(provider)

    async def save_generated_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        *,
        provider_id: UUID,
        expected_config_version: int,
        expected_model: str,
        structured_rubric: StructuredRubric,
    ) -> RubricView | None:
        async with self._database.sessions() as session, session.begin():
            provider = await session.scalar(
                select(ProviderConfig)
                .where(
                    ProviderConfig.id == provider_id,
                    ProviderConfig.status == "enabled",
                    ProviderConfig.config_version == expected_config_version,
                    ProviderConfig.tested_at.is_not(None),
                    ProviderConfig.tested_config_version == ProviderConfig.config_version,
                    ProviderConfig.default_model == expected_model,
                )
                .with_for_update()
            )
            if provider is None:
                return None
            await self._assume_teacher_role(session, owner_id)
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                    Assignment.status != "archived",
                )
                .with_for_update()
            )
            rubric = await session.scalar(
                select(RubricVersion)
                .where(
                    RubricVersion.id == rubric_id,
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                    RubricVersion.status == "draft",
                )
                .with_for_update()
            )
            if assignment is None or rubric is None:
                return None
            rubric.provider_config_id = provider_id
            rubric.model = expected_model
            rubric.structured_rubric = structured_rubric.model_dump(mode="json")
            await session.flush()
            return self._to_rubric(rubric)

    async def update_structured_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        structured_rubric: StructuredRubric,
    ) -> RubricView | None:
        async with self._teacher_session(owner_id) as session:
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                    Assignment.status != "archived",
                )
                .with_for_update()
            )
            rubric = await session.scalar(
                select(RubricVersion)
                .where(
                    RubricVersion.id == rubric_id,
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                    RubricVersion.status == "draft",
                    RubricVersion.provider_config_id.is_not(None),
                    RubricVersion.model.is_not(None),
                )
                .with_for_update()
            )
            if assignment is None or rubric is None:
                return None
            rubric.structured_rubric = structured_rubric.model_dump(mode="json")
            await session.flush()
            return self._to_rubric(rubric)

    async def confirm_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        *,
        provider_id: UUID,
        expected_model: str,
    ) -> AssignmentDetail | None:
        async with self._database.sessions() as session, session.begin():
            provider = await session.scalar(
                select(ProviderConfig)
                .where(
                    ProviderConfig.id == provider_id,
                    ProviderConfig.status == "enabled",
                    ProviderConfig.tested_at.is_not(None),
                    ProviderConfig.tested_config_version == ProviderConfig.config_version,
                    ProviderConfig.default_model == expected_model,
                )
                .with_for_update()
            )
            if provider is None:
                return None
            await self._assume_teacher_role(session, owner_id)
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                    Assignment.status != "archived",
                )
                .with_for_update()
            )
            target = await session.scalar(
                select(RubricVersion)
                .where(
                    RubricVersion.id == rubric_id,
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                    RubricVersion.status == "draft",
                    RubricVersion.provider_config_id == provider_id,
                    RubricVersion.model == expected_model,
                    RubricVersion.structured_rubric.is_not(None),
                )
                .with_for_update()
            )
            if assignment is None or target is None:
                return None

            if assignment.status == "ready":
                assignment.status = "draft"
                assignment.updated_at = datetime.now(UTC)
                await session.flush()

            current_confirmed = await session.scalar(
                select(RubricVersion)
                .where(
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                    RubricVersion.status == "confirmed",
                )
                .with_for_update()
            )
            if current_confirmed is not None:
                current_confirmed.status = "superseded"
                await session.flush()

            target.status = "confirmed"
            target.confirmed_at = datetime.now(UTC)
            await session.flush()
            assignment.status = "ready"
            assignment.updated_at = datetime.now(UTC)
            await session.flush()
            return await self._load_detail(session, owner_id, assignment_id)
