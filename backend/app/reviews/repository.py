"""阶段十一教师复核的 RLS 仓储与原子确认入口。"""

import json
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal, NoReturn, TypeVar, cast
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.domain.grading import DeductionResult, DimensionResult
from app.domain.models import (
    GradingAttempt,
    GradingJob,
    GradingJobItem,
    RubricVersion,
    Submission,
    TeacherReview,
)
from app.domain.rubric import StructuredRubric
from app.reviews.models import (
    ReviewAttemptView,
    ReviewConfirmationRef,
    ReviewConfirmationResult,
    ReviewCriterionInput,
    ReviewDeductionInput,
    ReviewDraftData,
    ReviewDraftView,
    ReviewEvidenceInput,
    ReviewItemStatus,
    ReviewJobStatus,
    ReviewJobSummary,
    ReviewQueueItem,
    ReviewRegradeTarget,
    ReviewTarget,
)
from app.reviews.service import (
    ReviewConflictError,
    ReviewDataError,
    ReviewNotFoundError,
    ReviewStateError,
    ReviewValidationError,
)

T = TypeVar("T")

# 仅转换复核写入中可安全归因为状态竞争的 SQLSTATE。
_REVIEW_CONFLICT_SQLSTATES = frozenset({"23503", "23505", "23P01", "40001"})


class SqlAlchemyReviewRepository:
    """所有教师查询使用真实教师角色；确认写入只经过 0015 函数。"""

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
    def _validated(adapter: TypeAdapter[T], value: object, code: str) -> T:
        try:
            return adapter.validate_python(value)
        except ValidationError as error:
            raise ReviewDataError(code, "复核数据库快照无效") from error

    @classmethod
    def _draft_view(cls, review: TeacherReview) -> ReviewDraftView:
        criteria = cls._validated(
            TypeAdapter(tuple[ReviewCriterionInput, ...]),
            review.criteria_results,
            "review_criteria_invalid",
        )
        deductions = cls._validated(
            TypeAdapter(tuple[ReviewDeductionInput, ...]),
            review.deduction_results,
            "review_deductions_invalid",
        )
        evidence = cls._validated(
            TypeAdapter(tuple[ReviewEvidenceInput, ...]),
            review.evidence,
            "review_evidence_invalid",
        )
        return ReviewDraftView(
            id=review.id,
            attempt_id=review.grading_attempt_id,
            revision_number=review.revision_number,
            status=cast(Literal["draft", "confirmed"], review.status),
            criteria=criteria,
            deductions=deductions,
            evidence=evidence,
            overall_feedback=review.feedback,
            change_reason=review.change_reason,
            subtotal=review.subtotal,
            deduction_total=review.deduction_total,
            final_score=review.final_score,
            confirmed_at=review.confirmed_at,
        )

    @classmethod
    async def _load_target(
        cls,
        session: AsyncSession,
        owner_id: UUID,
        item_id: UUID,
    ) -> ReviewTarget | None:
        row = (
            await session.execute(
                select(GradingJobItem, GradingJob, Submission, RubricVersion)
                .join(
                    GradingJob,
                    (GradingJob.id == GradingJobItem.grading_job_id)
                    & (GradingJob.owner_id == GradingJobItem.owner_id),
                )
                .join(
                    Submission,
                    (Submission.id == GradingJobItem.submission_id)
                    & (Submission.assignment_id == GradingJobItem.assignment_id)
                    & (Submission.owner_id == GradingJobItem.owner_id),
                )
                .join(
                    RubricVersion,
                    (RubricVersion.id == GradingJob.rubric_version_id)
                    & (RubricVersion.assignment_id == GradingJob.assignment_id)
                    & (RubricVersion.owner_id == GradingJob.owner_id),
                )
                .where(
                    GradingJobItem.id == item_id,
                    GradingJobItem.owner_id == owner_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        item, job, submission, rubric_row = row
        attempt = await session.scalar(
            select(GradingAttempt)
            .where(
                GradingAttempt.grading_job_item_id == item.id,
                GradingAttempt.owner_id == owner_id,
                GradingAttempt.status == "succeeded",
                GradingAttempt.scoring_round == item.dispatch_version,
            )
            .order_by(GradingAttempt.attempt_number.desc())
            .limit(1)
        )
        if attempt is None:
            return None
        review = await session.scalar(
            select(TeacherReview).where(
                TeacherReview.grading_attempt_id == attempt.id,
                TeacherReview.grading_job_item_id == item.id,
                TeacherReview.owner_id == owner_id,
            )
        )
        try:
            if (
                rubric_row.structured_rubric is None
                or attempt.subtotal is None
                or attempt.deduction_total is None
                or attempt.total_score is None
                or attempt.criteria_results is None
                or attempt.deduction_results is None
                or attempt.overall_feedback is None
            ):
                raise ValueError("复核 attempt 缺少成功结果")
            rubric = StructuredRubric.model_validate(rubric_row.structured_rubric)
            dimensions = TypeAdapter(tuple[DimensionResult, ...]).validate_python(
                attempt.criteria_results
            )
            deductions = TypeAdapter(tuple[DeductionResult, ...]).validate_python(
                attempt.deduction_results
            )
        except (ValidationError, ValueError) as error:
            raise ReviewDataError("review_attempt_invalid", "模型评分快照无效") from error
        return ReviewTarget(
            owner_id=owner_id,
            job_id=job.id,
            item_id=item.id,
            item_status=item.status,
            assignment_id=job.assignment_id,
            assignment_title=job.assignment_title_snapshot,
            assignment_instructions=job.assignment_instructions_snapshot,
            rubric_version_id=rubric_row.id,
            rubric_version=rubric_row.version,
            rubric=rubric,
            submission_id=submission.id,
            original_filename=submission.original_filename,
            submission_status=submission.status,
            extracted_object_key=submission.extracted_object_key,
            attempt=ReviewAttemptView(
                id=attempt.id,
                attempt_number=attempt.attempt_number,
                scoring_round=attempt.scoring_round,
                model=job.model,
                subtotal=attempt.subtotal,
                deduction_total=attempt.deduction_total,
                total_score=attempt.total_score,
                dimensions=dimensions,
                deductions=deductions,
                overall_feedback=attempt.overall_feedback,
            ),
            draft=cls._draft_view(review) if review is not None else None,
        )

    async def get_target(self, owner_id: UUID, item_id: UUID) -> ReviewTarget | None:
        async with self._teacher_session(owner_id) as session:
            return await self._load_target(session, owner_id, item_id)

    async def get_regrade_target(
        self,
        owner_id: UUID,
        item_id: UUID,
    ) -> ReviewRegradeTarget | None:
        async with self._teacher_session(owner_id) as session:
            row = (
                await session.execute(
                    select(GradingJobItem, GradingJob)
                    .join(
                        GradingJob,
                        (GradingJob.id == GradingJobItem.grading_job_id)
                        & (GradingJob.owner_id == GradingJobItem.owner_id),
                    )
                    .where(
                        GradingJobItem.id == item_id,
                        GradingJobItem.owner_id == owner_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            item, job = row
            confirmed_review_id = await session.scalar(
                select(TeacherReview.id).where(
                    TeacherReview.grading_job_item_id == item.id,
                    TeacherReview.owner_id == owner_id,
                    TeacherReview.status == "confirmed",
                )
            )
            return ReviewRegradeTarget(
                job_id=job.id,
                item_id=item.id,
                item_status=cast(ReviewItemStatus, item.status),
                has_confirmed_review=confirmed_review_id is not None,
            )

    async def list_jobs(self, owner_id: UUID) -> tuple[ReviewJobSummary, ...]:
        async with self._teacher_session(owner_id) as session:
            jobs = list(
                (
                    await session.scalars(
                        select(GradingJob)
                        .where(GradingJob.owner_id == owner_id)
                        .order_by(GradingJob.created_at.desc(), GradingJob.id)
                        .limit(100)
                    )
                ).all()
            )
            if not jobs:
                return ()
            rows = list(
                (
                    await session.execute(
                        select(GradingJobItem, Submission)
                        .join(
                            Submission,
                            (Submission.id == GradingJobItem.submission_id)
                            & (Submission.owner_id == GradingJobItem.owner_id),
                        )
                        .where(
                            GradingJobItem.grading_job_id.in_([job.id for job in jobs]),
                            GradingJobItem.owner_id == owner_id,
                        )
                        .order_by(
                            GradingJobItem.grading_job_id,
                            GradingJobItem.position,
                        )
                    )
                ).all()
            )
            rows_by_job: dict[UUID, list[tuple[GradingJobItem, Submission]]] = defaultdict(list)
            for item, submission in rows:
                rows_by_job[item.grading_job_id].append((item, submission))
            item_ids = [item.id for item, _submission in rows]
            attempt_counts: dict[UUID, int] = {}
            reviewable_item_ids: set[UUID] = set()
            review_refs: dict[UUID, TeacherReview] = {}
            if item_ids:
                attempts = (
                    await session.execute(
                        select(
                            GradingAttempt.grading_job_item_id,
                            func.count(GradingAttempt.id),
                        )
                        .where(
                            GradingAttempt.owner_id == owner_id,
                            GradingAttempt.grading_job_item_id.in_(item_ids),
                        )
                        .group_by(GradingAttempt.grading_job_item_id)
                    )
                ).tuples()
                attempt_counts = {
                    attempt_item_id: attempt_count for attempt_item_id, attempt_count in attempts
                }
                reviewable_item_ids = set(
                    (
                        await session.execute(
                            select(GradingAttempt.grading_job_item_id)
                            .join(
                                GradingJobItem,
                                GradingJobItem.id == GradingAttempt.grading_job_item_id,
                            )
                            .where(
                                GradingAttempt.owner_id == owner_id,
                                GradingAttempt.grading_job_item_id.in_(item_ids),
                                GradingAttempt.status == "succeeded",
                                GradingAttempt.scoring_round == GradingJobItem.dispatch_version,
                            )
                            .distinct()
                        )
                    )
                    .scalars()
                    .all()
                )
                review_rows = list(
                    (
                        await session.execute(
                            select(
                                GradingAttempt.grading_job_item_id,
                                GradingAttempt.attempt_number,
                                TeacherReview,
                            )
                            .join(
                                GradingJobItem,
                                GradingJobItem.id == GradingAttempt.grading_job_item_id,
                            )
                            .join(
                                TeacherReview,
                                TeacherReview.grading_attempt_id == GradingAttempt.id,
                            )
                            .where(
                                GradingAttempt.owner_id == owner_id,
                                GradingAttempt.grading_job_item_id.in_(item_ids),
                                GradingAttempt.status == "succeeded",
                                GradingAttempt.scoring_round == GradingJobItem.dispatch_version,
                            )
                            .order_by(GradingAttempt.attempt_number.desc())
                        )
                    ).all()
                )
                for review_item_id, _attempt_number, review in review_rows:
                    review_refs.setdefault(review_item_id, review)
            summaries: list[ReviewJobSummary] = []
            for job in jobs:
                job_rows = rows_by_job[job.id]
                counts = Counter(item.status for item, _submission in job_rows)
                summaries.append(
                    ReviewJobSummary(
                        id=job.id,
                        assignment_id=job.assignment_id,
                        assignment_title=job.assignment_title_snapshot,
                        model=job.model,
                        status=cast(ReviewJobStatus, job.status),
                        total=job.expected_item_count,
                        needs_review=counts["needs_review"],
                        completed=counts["completed"],
                        failed=counts["failed"],
                        items=tuple(
                            ReviewQueueItem(
                                id=item.id,
                                submission_id=submission.id,
                                original_filename=submission.original_filename,
                                position=item.position,
                                status=cast(ReviewItemStatus, item.status),
                                attempt_count=attempt_counts.get(item.id, 0),
                                error_code=item.error_code,
                                review_available=item.id in reviewable_item_ids,
                                review_id=(
                                    review_refs[item.id].id if item.id in review_refs else None
                                ),
                                review_revision=(
                                    review_refs[item.id].revision_number
                                    if item.id in review_refs
                                    else None
                                ),
                                review_status=(
                                    cast(
                                        Literal["draft", "confirmed"],
                                        review_refs[item.id].status,
                                    )
                                    if item.id in review_refs
                                    else None
                                ),
                            )
                            for item, submission in job_rows
                        ),
                        created_at=job.created_at,
                        finished_at=job.finished_at,
                    )
                )
            return tuple(summaries)

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    async def _save(
        cls,
        session: AsyncSession,
        item_id: UUID,
        data: ReviewDraftData,
    ) -> UUID | None:
        return cast(
            UUID | None,
            await session.scalar(
                text(
                    "select paper_grading_private.save_teacher_review_draft("
                    "cast(:item_id as uuid), cast(:attempt_id as uuid), "
                    "cast(:criteria as jsonb), cast(:deductions as jsonb), "
                    "cast(:evidence as jsonb), :feedback, :change_reason, "
                    ":subtotal, :deduction_total, :final_score)"
                ),
                {
                    "item_id": item_id,
                    "attempt_id": data.attempt_id,
                    "criteria": cls._json([item.model_dump(mode="json") for item in data.criteria]),
                    "deductions": cls._json(
                        [item.model_dump(mode="json") for item in data.deductions]
                    ),
                    "evidence": cls._json([item.model_dump(mode="json") for item in data.evidence]),
                    "feedback": data.overall_feedback,
                    "change_reason": data.change_reason,
                    "subtotal": data.subtotal,
                    "deduction_total": data.deduction_total,
                    "final_score": data.final_score,
                },
            ),
        )

    @staticmethod
    def _confirmation_payload(reviews: tuple[ReviewConfirmationRef, ...]) -> str:
        return json.dumps(
            [
                {
                    "review_id": str(review.review_id),
                    "revision_number": review.revision_number,
                }
                for review in reviews
            ],
            separators=(",", ":"),
        )

    @classmethod
    async def _confirm(
        cls,
        session: AsyncSession,
        reviews: tuple[ReviewConfirmationRef, ...],
    ) -> tuple[UUID, ...] | None:
        value = await session.scalar(
            text("select paper_grading_private.confirm_teacher_reviews(cast(:reviews as jsonb))"),
            {"reviews": cls._confirmation_payload(reviews)},
        )
        return tuple(value) if value is not None else None

    @staticmethod
    def _sqlstate(error: DBAPIError) -> str | None:
        source: object | None = error.orig
        for _index in range(3):
            value = getattr(source, "sqlstate", None) or getattr(source, "pgcode", None)
            if isinstance(value, str):
                return value
            source = getattr(source, "__cause__", None)
        return None

    @classmethod
    def _raise_database_error(cls, error: DBAPIError) -> NoReturn:
        sqlstate = cls._sqlstate(error)
        if sqlstate == "23514":
            raise ReviewValidationError(
                "review_database_validation_failed",
                "复核数据未通过数据库契约",
            ) from error
        if sqlstate in _REVIEW_CONFLICT_SQLSTATES:
            raise ReviewConflictError("复核状态已被并发修改") from error
        raise error

    @classmethod
    async def _result(
        cls,
        session: AsyncSession,
        owner_id: UUID,
        reviews: tuple[ReviewConfirmationRef, ...],
    ) -> ReviewConfirmationResult:
        rows = list(
            (
                await session.scalars(
                    select(TeacherReview)
                    .where(
                        TeacherReview.owner_id == owner_id,
                        TeacherReview.id.in_([review.review_id for review in reviews]),
                    )
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(reviews):
            raise ReviewNotFoundError("复核任务不存在")
        item_rows = list(
            (
                await session.execute(
                    select(GradingJobItem.grading_job_id, GradingJob.status)
                    .join(
                        GradingJob,
                        (GradingJob.id == GradingJobItem.grading_job_id)
                        & (GradingJob.owner_id == GradingJobItem.owner_id),
                    )
                    .where(
                        GradingJobItem.owner_id == owner_id,
                        GradingJobItem.id.in_([row.grading_job_item_id for row in rows]),
                    )
                )
            ).all()
        )
        completed_job_ids = tuple(
            sorted(
                {job_id for job_id, status in item_rows if status == "completed"},
                key=str,
            )
        )
        return ReviewConfirmationResult(
            reviews=tuple(cls._draft_view(by_id[reference.review_id]) for reference in reviews),
            completed_job_ids=completed_job_ids,
        )

    async def save_draft(
        self,
        owner_id: UUID,
        item_id: UUID,
        data: ReviewDraftData,
    ) -> ReviewDraftView:
        try:
            async with self._teacher_session(owner_id) as session:
                review_id = await self._save(session, item_id, data)
                if review_id is None:
                    raise ReviewStateError("复核草稿状态已变化")
                review = await session.scalar(
                    select(TeacherReview)
                    .where(TeacherReview.id == review_id, TeacherReview.owner_id == owner_id)
                    .execution_options(populate_existing=True)
                )
                if review is None:
                    raise ReviewNotFoundError("复核任务不存在")
                return self._draft_view(review)
        except DBAPIError as error:
            self._raise_database_error(error)

    async def save_and_confirm(
        self,
        owner_id: UUID,
        job_id: UUID,
        item_id: UUID,
        data: ReviewDraftData,
    ) -> ReviewConfirmationResult:
        try:
            async with self._teacher_session(owner_id) as session:
                target = await self._load_target(session, owner_id, item_id)
                if target is None or target.job_id != job_id:
                    raise ReviewNotFoundError("复核任务不存在")
                if target.item_status == "completed" and target.draft is not None:
                    reference = ReviewConfirmationRef(
                        item_id=item_id,
                        review_id=target.draft.id,
                        revision_number=target.draft.revision_number,
                    )
                else:
                    review_id = await self._save(session, item_id, data)
                    if review_id is None:
                        raise ReviewConflictError("复核草稿状态已经变化")
                    review = await session.scalar(
                        select(TeacherReview).where(
                            TeacherReview.id == review_id,
                            TeacherReview.owner_id == owner_id,
                        )
                    )
                    if review is None:
                        raise ReviewNotFoundError("复核任务不存在")
                    reference = ReviewConfirmationRef(
                        item_id=item_id,
                        review_id=review.id,
                        revision_number=review.revision_number,
                    )
                references = (reference,)
                if await self._confirm(session, references) is None:
                    raise ReviewConflictError("复核确认状态已经变化")
                return await self._result(session, owner_id, references)
        except DBAPIError as error:
            self._raise_database_error(error)

    async def confirm_reviews(
        self,
        owner_id: UUID,
        job_id: UUID,
        reviews: tuple[ReviewConfirmationRef, ...],
    ) -> ReviewConfirmationResult:
        try:
            async with self._teacher_session(owner_id) as session:
                for reference in reviews:
                    target = await self._load_target(session, owner_id, reference.item_id)
                    if (
                        target is None
                        or target.job_id != job_id
                        or target.draft is None
                        or target.draft.id != reference.review_id
                        or target.draft.revision_number != reference.revision_number
                    ):
                        raise ReviewNotFoundError("复核任务不存在")
                if await self._confirm(session, reviews) is None:
                    raise ReviewConflictError("批量复核状态已经变化")
                return await self._result(session, owner_id, reviews)
        except DBAPIError as error:
            self._raise_database_error(error)
