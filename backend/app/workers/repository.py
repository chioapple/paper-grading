"""阶段十批次创建、读取和教师控制的 PostgreSQL 实现。"""

import json
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.domain.enums import ProviderType
from app.domain.models import (
    Assignment,
    GradingAttempt,
    GradingJob,
    GradingJobItem,
    ProviderConfig,
    RubricVersion,
    Submission,
)
from app.domain.rubric import StructuredRubric
from app.grading.prompt import build_grading_contract_snapshot
from app.monitoring.repository import QuotaGateResult, SqlAlchemyQuotaRepository
from app.providers.base import ProviderModelProfile
from app.workers.models import (
    GradingJobCreate,
    GradingJobCreation,
    GradingJobItemView,
    GradingJobView,
    GradingProviderSnapshot,
    ItemStatus,
    JobStatus,
)
from app.workers.service import (
    GradingJobConfigurationError,
    GradingJobIdempotencyConflict,
)
from app.workers.tasks import (
    AttemptKind,
    GradingAttemptClaim,
    GradingAttemptCompletion,
    GradingAttemptFailure,
    GradingItemPreparation,
)

GRADING_JOB_BASE_RESERVATION_BYTES = 64 * 1024
GRADING_JOB_ITEM_RESERVATION_BYTES = 256 * 1024


class DatabaseQuotaGate(Protocol):
    async def check_database_growth(
        self,
        session: AsyncSession,
        *,
        operation_key: str,
        requested_bytes: int,
    ) -> QuotaGateResult: ...


class SqlAlchemyGradingJobRepository:
    """教师写入受 RLS 保护；供应商快照只由后端可信事务读取。"""

    def __init__(
        self,
        database: Database,
        *,
        quota: DatabaseQuotaGate | None = None,
    ) -> None:
        self._database = database
        self._quota = quota or SqlAlchemyQuotaRepository(database)

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

    @asynccontextmanager
    async def _worker_session(self) -> AsyncIterator[AsyncSession]:
        async with self._database.sessions() as session, session.begin():
            await session.execute(text("set local role paper_grading_worker"))
            yield session

    @staticmethod
    async def _load_job(
        session: AsyncSession,
        owner_id: UUID,
        job_id: UUID,
    ) -> GradingJobView | None:
        job = await session.scalar(
            select(GradingJob).where(GradingJob.id == job_id, GradingJob.owner_id == owner_id)
        )
        if job is None:
            return None
        items = list(
            (
                await session.scalars(
                    select(GradingJobItem)
                    .where(
                        GradingJobItem.grading_job_id == job_id,
                        GradingJobItem.owner_id == owner_id,
                    )
                    .order_by(GradingJobItem.position)
                )
            ).all()
        )
        attempts: dict[UUID, int] = {}
        if items:
            attempt_rows = (
                await session.execute(
                    select(GradingAttempt.grading_job_item_id, func.count(GradingAttempt.id))
                    .where(GradingAttempt.owner_id == owner_id)
                    .where(GradingAttempt.grading_job_item_id.in_([item.id for item in items]))
                    .group_by(GradingAttempt.grading_job_item_id)
                )
            ).tuples()
            attempts = {item_id: count for item_id, count in attempt_rows}
        counts = Counter(item.status for item in items)
        item_views = tuple(
            GradingJobItemView(
                id=item.id,
                submission_id=item.submission_id,
                position=item.position,
                status=cast(ItemStatus, item.status),
                dispatch_version=item.dispatch_version,
                attempt_count=attempts.get(item.id, 0),
                error_code=item.error_code,
            )
            for item in items
        )
        return GradingJobView(
            id=job.id,
            assignment_id=job.assignment_id,
            rubric_version_id=job.rubric_version_id,
            model=job.model,
            status=cast(JobStatus, job.status),
            state_version=job.state_version,
            total=job.expected_item_count,
            queued=counts["queued"],
            running=counts["running"],
            needs_review=counts["needs_review"],
            completed=counts["completed"],
            failed=counts["failed"],
            cancelled=counts["cancelled"],
            items=item_views,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    async def create_or_get_job(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: GradingJobCreate,
    ) -> GradingJobCreation:
        request_hash = payload.request_hash(assignment_id)
        async with self._database.sessions() as session, session.begin():
            await self._assume_teacher_role(session, owner_id)
            existing_id = await session.scalar(
                select(GradingJob.id).where(
                    GradingJob.owner_id == owner_id,
                    GradingJob.idempotency_key == payload.idempotency_key,
                )
            )
            if existing_id is not None:
                existing = await session.scalar(
                    select(GradingJob).where(
                        GradingJob.id == existing_id,
                        GradingJob.owner_id == owner_id,
                    )
                )
                if existing is None:
                    raise GradingJobConfigurationError("评分批次不可见")
                if existing.request_hash != request_hash:
                    raise GradingJobIdempotencyConflict("同一幂等键对应了不同批次请求")
                job = await self._load_job(session, owner_id, existing.id)
                if job is None:
                    raise GradingJobConfigurationError("幂等批次读取失败")
                return GradingJobCreation(job=job, created=False)

            await self._quota.check_database_growth(
                session,
                operation_key=f"grading-job:{owner_id}:{payload.idempotency_key}",
                requested_bytes=(
                    GRADING_JOB_BASE_RESERVATION_BYTES
                    + len(payload.submission_ids) * GRADING_JOB_ITEM_RESERVATION_BYTES
                ),
            )
            assignment = await session.scalar(
                select(Assignment)
                .where(
                    Assignment.id == assignment_id,
                    Assignment.owner_id == owner_id,
                    Assignment.status == "ready",
                )
                .with_for_update()
            )
            rubric = await session.scalar(
                select(RubricVersion)
                .where(
                    RubricVersion.assignment_id == assignment_id,
                    RubricVersion.owner_id == owner_id,
                    RubricVersion.status == "confirmed",
                )
                .with_for_update()
            )
            if (
                assignment is None
                or rubric is None
                or rubric.structured_rubric is None
                or rubric.provider_config_id is None
                or rubric.model is None
            ):
                raise GradingJobConfigurationError(
                    "作业或评分标准状态已变化",
                    code="grading_job_assignment_invalid",
                )
            rows = list(
                (
                    await session.scalars(
                        select(Submission).where(
                            Submission.id.in_(payload.submission_ids),
                            Submission.assignment_id == assignment_id,
                            Submission.owner_id == owner_id,
                            Submission.status == "ready",
                        )
                    )
                ).all()
            )
            submissions = {row.id: row for row in rows}
            if set(submissions) != set(payload.submission_ids):
                raise GradingJobConfigurationError(
                    "批次包含不存在或尚未解析完成的论文",
                    code="grading_job_submissions_invalid",
                )

            structured_rubric = StructuredRubric.model_validate(rubric.structured_rubric)
            contract = build_grading_contract_snapshot(structured_rubric)

            await session.execute(text("set local role none"))
            provider = await session.scalar(
                select(ProviderConfig)
                .where(ProviderConfig.id == rubric.provider_config_id)
                .with_for_update()
            )
            if (
                provider is None
                or provider.status != "enabled"
                or provider.tested_config_version != provider.config_version
                or provider.default_model is None
                or provider.default_model != rubric.model
            ):
                raise GradingJobConfigurationError(
                    "供应商当前配置不可用于评分",
                    code="grading_job_provider_invalid",
                )
            profile_payload = provider.model_profiles.get(provider.default_model)
            if profile_payload is None:
                raise GradingJobConfigurationError(
                    "默认模型缺少管理员确认的能力快照",
                    code="grading_job_provider_invalid",
                )
            model_profile = ProviderModelProfile.model_validate(profile_payload)
            provider_snapshot = GradingProviderSnapshot(
                provider_type=cast(ProviderType, provider.provider_type),
                base_url=provider.base_url,
                timeout_seconds=provider.timeout_seconds,
                max_concurrency=provider.max_concurrency,
                model_profile=model_profile,
            )
            await self._assume_teacher_role(session, owner_id)

            job_id = uuid4()
            created_id = await session.scalar(
                insert(GradingJob)
                .values(
                    id=job_id,
                    owner_id=owner_id,
                    assignment_id=assignment_id,
                    rubric_version_id=rubric.id,
                    provider_config_id=provider.id,
                    provider_config_version=provider.config_version,
                    assignment_title_snapshot=assignment.title,
                    assignment_instructions_snapshot=assignment.instructions,
                    expected_item_count=len(payload.submission_ids),
                    request_hash=request_hash,
                    model=provider.default_model,
                    model_parameters=provider_snapshot.model_dump(mode="json"),
                    model_parameters_hash=provider_snapshot.snapshot_hash(),
                    prompt_version=contract.prompt_version,
                    prompt_hash=contract.prompt_hash,
                    result_schema_version=contract.result_schema_version,
                    result_schema=contract.result_schema,
                    result_schema_hash=contract.result_schema_hash,
                    rubric_hash=contract.rubric_hash,
                    idempotency_key=payload.idempotency_key,
                    status="queued",
                    state_version=1,
                )
                .on_conflict_do_nothing(index_elements=["owner_id", "idempotency_key"])
                .returning(GradingJob.id)
            )
            if created_id is None:
                concurrent = await session.scalar(
                    select(GradingJob).where(
                        GradingJob.owner_id == owner_id,
                        GradingJob.idempotency_key == payload.idempotency_key,
                    )
                )
                if concurrent is None or concurrent.request_hash != request_hash:
                    raise GradingJobIdempotencyConflict("同一幂等键对应了不同批次请求")
                job = await self._load_job(session, owner_id, concurrent.id)
                if job is None:
                    raise GradingJobConfigurationError("并发幂等批次读取失败")
                return GradingJobCreation(job=job, created=False)

            session.add_all(
                [
                    GradingJobItem(
                        id=uuid4(),
                        owner_id=owner_id,
                        assignment_id=assignment_id,
                        grading_job_id=job_id,
                        submission_id=submission_id,
                        position=position,
                        status="queued",
                        dispatch_version=1,
                        retry_count=0,
                    )
                    for position, submission_id in enumerate(payload.submission_ids)
                ]
            )
            await session.flush()
            job = await self._load_job(session, owner_id, job_id)
            if job is None:
                raise GradingJobConfigurationError("评分批次创建后读取失败")
            return GradingJobCreation(job=job, created=True)

    async def get_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView | None:
        async with self._teacher_session(owner_id) as session:
            return await self._load_job(session, owner_id, job_id)

    async def control_job(
        self,
        owner_id: UUID,
        job_id: UUID,
        action: str,
        item_id: UUID | None = None,
    ) -> GradingJobView | None:
        async with self._teacher_session(owner_id) as session:
            controlled_id = cast(
                UUID | None,
                await session.scalar(
                    text(
                        "select paper_grading_private.control_grading_job("
                        "cast(:job_id as uuid), :action, cast(:item_id as uuid))"
                    ),
                    {"job_id": job_id, "action": action, "item_id": item_id},
                ),
            )
            if controlled_id is None:
                return None
            return await self._load_job(session, owner_id, controlled_id)

    async def list_dispatchable_items(self, *, limit: int = 500) -> list[tuple[UUID, int]]:
        """Redis 丢消息可重复扫描；claim 仍是唯一调用供应商的门禁。"""

        async with self._worker_session() as session:
            rows = (
                await session.execute(
                    select(GradingJobItem.id, GradingJobItem.dispatch_version)
                    .join(GradingJob, GradingJob.id == GradingJobItem.grading_job_id)
                    .where(
                        GradingJobItem.status == "queued",
                        GradingJobItem.available_at <= func.now(),
                        GradingJob.status.in_(("queued", "running")),
                    )
                    .order_by(GradingJob.created_at, GradingJobItem.position)
                    .limit(limit)
                )
            ).all()
            return [(item_id, version) for item_id, version in rows]

    async def expire_stale_attempts(self, *, limit: int = 100) -> int:
        """调用开始后 Worker 丢失一律视为结果未知，禁止自动再次计费。"""

        now = datetime.now(UTC)
        expired = 0
        async with self._worker_session() as session:
            candidates = (
                await session.execute(
                    select(GradingJobItem.grading_job_id, GradingJobItem.id)
                    .where(
                        GradingJobItem.status == "running",
                        GradingJobItem.lease_expires_at <= func.now(),
                    )
                    .order_by(GradingJobItem.lease_expires_at, GradingJobItem.id)
                    .limit(limit)
                )
            ).all()
            for job_id, item_id in candidates:
                job = await session.scalar(
                    select(GradingJob).where(GradingJob.id == job_id).with_for_update()
                )
                item = await session.scalar(
                    select(GradingJobItem)
                    .where(
                        GradingJobItem.id == item_id,
                        GradingJobItem.status == "running",
                        GradingJobItem.lease_expires_at <= func.now(),
                    )
                    .with_for_update()
                )
                if job is None or item is None:
                    continue
                attempt = await session.scalar(
                    select(GradingAttempt)
                    .where(
                        GradingAttempt.grading_job_item_id == item.id,
                        GradingAttempt.status == "running",
                    )
                    .with_for_update()
                )
                if attempt is None:
                    raise RuntimeError("运行中的论文没有唯一 running attempt")
                attempt.status = "failed"
                attempt.provider_call_state = "ambiguous"
                attempt.error_code = "provider_call_outcome_unknown"
                attempt.error_details = {"reason": "worker_lease_expired"}
                attempt.finished_at = now
                item.status = "needs_review"
                item.finished_at = now
                item.lease_token = None
                item.lease_expires_at = None
                item.error_code = "provider_call_outcome_unknown"
                item.updated_at = now
                await session.flush()
                await self._reconcile_job(session, job, now)
                expired += 1
        return expired

    async def prepare_item(
        self,
        item_id: UUID,
        dispatch_version: int,
    ) -> GradingItemPreparation | None:
        async with self._worker_session() as session:
            row = (
                await session.execute(
                    select(GradingJobItem, GradingJob, Submission, RubricVersion, ProviderConfig)
                    .join(
                        GradingJob,
                        (GradingJob.id == GradingJobItem.grading_job_id)
                        & (GradingJob.owner_id == GradingJobItem.owner_id),
                    )
                    .join(
                        Submission,
                        (Submission.id == GradingJobItem.submission_id)
                        & (Submission.owner_id == GradingJobItem.owner_id),
                    )
                    .join(
                        RubricVersion,
                        (RubricVersion.id == GradingJob.rubric_version_id)
                        & (RubricVersion.owner_id == GradingJob.owner_id),
                    )
                    .join(ProviderConfig, ProviderConfig.id == GradingJob.provider_config_id)
                    .where(
                        GradingJobItem.id == item_id,
                        GradingJobItem.dispatch_version == dispatch_version,
                        GradingJobItem.status == "queued",
                        GradingJobItem.available_at <= func.now(),
                        GradingJob.status.in_(("queued", "running")),
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            item, job, submission, rubric, provider = row
            if (
                submission.status != "ready"
                or submission.extracted_object_key is None
                or rubric.status != "confirmed"
                or rubric.structured_rubric is None
                or provider.config_version != job.provider_config_version
                or provider.encrypted_api_key is None
                or provider.api_key_nonce is None
            ):
                raise GradingJobConfigurationError("评分任务的不可变输入已经失效")
            provider_snapshot = GradingProviderSnapshot.model_validate(job.model_parameters)
            if provider_snapshot.snapshot_hash() != job.model_parameters_hash:
                raise GradingJobConfigurationError("供应商能力快照哈希不一致")
            structured_rubric = StructuredRubric.model_validate(rubric.structured_rubric)
            last_attempt = await session.scalar(
                select(GradingAttempt)
                .where(GradingAttempt.grading_job_item_id == item.id)
                .order_by(GradingAttempt.attempt_number.desc())
                .limit(1)
            )
            correction_source = await session.scalar(
                select(GradingAttempt)
                .where(
                    GradingAttempt.grading_job_item_id == item.id,
                    GradingAttempt.scoring_round == item.dispatch_version,
                    GradingAttempt.error_code == "grade_output_correction_required",
                )
                .order_by(GradingAttempt.attempt_number.desc())
                .limit(1)
            )
            attempt_kind: AttemptKind
            parent_attempt_id: UUID | None
            if correction_source is not None:
                attempt_kind = (
                    "correction"
                    if last_attempt is not None and last_attempt.id == correction_source.id
                    else "automatic_retry"
                )
                parent_attempt_id = (
                    last_attempt.id if last_attempt is not None else correction_source.id
                )
                previous_response_object_key = correction_source.raw_response_object_key
                previous_error_details = correction_source.error_details
            elif dispatch_version > 1 and (
                last_attempt is None or last_attempt.scoring_round < dispatch_version
            ):
                attempt_kind = "manual_retry"
                parent_attempt_id = last_attempt.id if last_attempt is not None else None
                previous_response_object_key = None
                previous_error_details = None
            elif last_attempt is not None:
                attempt_kind = "automatic_retry"
                parent_attempt_id = last_attempt.id
                previous_response_object_key = None
                previous_error_details = None
            else:
                attempt_kind = "initial"
                parent_attempt_id = None
                previous_response_object_key = None
                previous_error_details = None
            return GradingItemPreparation(
                owner_id=item.owner_id,
                job_id=job.id,
                item_id=item.id,
                dispatch_version=item.dispatch_version,
                submission_id=submission.id,
                extracted_object_key=submission.extracted_object_key,
                assignment_id=job.assignment_id,
                assignment_title=job.assignment_title_snapshot,
                assignment_instructions=job.assignment_instructions_snapshot,
                rubric_version_id=rubric.id,
                rubric_version=rubric.version,
                rubric=structured_rubric,
                provider_config_id=provider.id,
                provider_config_version=provider.config_version,
                encrypted_api_key=provider.encrypted_api_key,
                api_key_nonce=provider.api_key_nonce,
                model=job.model,
                provider_snapshot=provider_snapshot,
                prompt_version=job.prompt_version,
                prompt_hash=job.prompt_hash,
                result_schema_version=job.result_schema_version,
                result_schema=job.result_schema,
                result_schema_hash=job.result_schema_hash,
                rubric_hash=job.rubric_hash,
                attempt_kind=attempt_kind,
                parent_attempt_id=parent_attempt_id,
                previous_response_object_key=previous_response_object_key,
                previous_error_details=previous_error_details,
            )

    async def claim_attempt(
        self,
        prepared: GradingItemPreparation,
        request_hash: bytes,
    ) -> GradingAttemptClaim | None:
        now = datetime.now(UTC)
        async with self._worker_session() as session:
            await session.execute(
                text("select pg_advisory_xact_lock(hashtextextended(:provider_id, 0))"),
                {"provider_id": str(prepared.provider_config_id)},
            )
            running_count = cast(
                int,
                await session.scalar(
                    select(func.count(GradingAttempt.id))
                    .join(
                        GradingJobItem,
                        GradingJobItem.id == GradingAttempt.grading_job_item_id,
                    )
                    .join(GradingJob, GradingJob.id == GradingJobItem.grading_job_id)
                    .where(
                        GradingJob.provider_config_id == prepared.provider_config_id,
                        GradingAttempt.status == "running",
                    )
                ),
            )
            if running_count >= prepared.provider_snapshot.max_concurrency:
                return None
            item_pointer = (
                await session.execute(
                    select(GradingJobItem.grading_job_id).where(
                        GradingJobItem.id == prepared.item_id,
                        GradingJobItem.owner_id == prepared.owner_id,
                    )
                )
            ).scalar_one_or_none()
            if item_pointer is None:
                return None
            job = await session.scalar(
                select(GradingJob)
                .where(
                    GradingJob.id == item_pointer,
                    GradingJob.owner_id == prepared.owner_id,
                    GradingJob.status.in_(("queued", "running")),
                )
                .with_for_update()
            )
            item = await session.scalar(
                select(GradingJobItem)
                .where(
                    GradingJobItem.id == prepared.item_id,
                    GradingJobItem.owner_id == prepared.owner_id,
                    GradingJobItem.dispatch_version == prepared.dispatch_version,
                    GradingJobItem.status == "queued",
                    GradingJobItem.available_at <= func.now(),
                )
                .with_for_update()
            )
            if job is None or item is None:
                return None
            attempt_number = (
                cast(
                    int,
                    await session.scalar(
                        select(func.coalesce(func.max(GradingAttempt.attempt_number), 0)).where(
                            GradingAttempt.grading_job_item_id == item.id
                        )
                    ),
                )
                + 1
            )
            call_sequence = (
                cast(
                    int,
                    await session.scalar(
                        select(func.coalesce(func.max(GradingAttempt.call_sequence), 0)).where(
                            GradingAttempt.grading_job_item_id == item.id,
                            GradingAttempt.scoring_round == item.dispatch_version,
                        )
                    ),
                )
                + 1
            )
            lease_token = uuid4()
            attempt = GradingAttempt(
                id=uuid4(),
                owner_id=item.owner_id,
                grading_job_item_id=item.id,
                parent_attempt_id=prepared.parent_attempt_id,
                attempt_number=attempt_number,
                scoring_round=item.dispatch_version,
                call_sequence=call_sequence,
                attempt_kind=prepared.attempt_kind,
                status="running",
                provider_call_started_at=now,
                provider_call_state="started",
                request_version="grade-request.v1",
                request_hash=request_hash,
                idempotency_key=(
                    f"{item.id}:{item.dispatch_version}:{call_sequence}:{request_hash.hex()}"
                ),
                max_score=prepared.rubric.total_score,
            )
            session.add(attempt)
            item.status = "running"
            item.started_at = item.started_at or now
            item.lease_token = lease_token
            item.lease_expires_at = now + timedelta(
                seconds=float(prepared.provider_snapshot.timeout_seconds) + 30
            )
            item.updated_at = now
            if job.status == "queued":
                job.status = "running"
                job.started_at = job.started_at or now
            job.state_version += 1
            job.updated_at = now
            await session.flush()
            return GradingAttemptClaim(
                attempt_id=attempt.id,
                attempt_number=attempt.attempt_number,
                scoring_round=attempt.scoring_round,
                call_sequence=attempt.call_sequence,
                lease_token=lease_token,
                request_hash=attempt.request_hash,
            )

    async def finish_success(
        self,
        claim: GradingAttemptClaim,
        completion: GradingAttemptCompletion,
    ) -> None:
        now = datetime.now(UTC)
        async with self._worker_session() as session:
            attempt_pointer = (
                await session.execute(
                    select(
                        GradingAttempt.grading_job_item_id,
                        GradingAttempt.owner_id,
                    ).where(GradingAttempt.id == claim.attempt_id)
                )
            ).one_or_none()
            if attempt_pointer is None:
                raise RuntimeError("评分 attempt 不存在")
            item_pointer = (
                await session.execute(
                    select(GradingJobItem.grading_job_id).where(
                        GradingJobItem.id == attempt_pointer.grading_job_item_id,
                        GradingJobItem.owner_id == attempt_pointer.owner_id,
                    )
                )
            ).scalar_one()
            job = await session.scalar(
                select(GradingJob).where(GradingJob.id == item_pointer).with_for_update()
            )
            item = await session.scalar(
                select(GradingJobItem)
                .where(GradingJobItem.id == attempt_pointer.grading_job_item_id)
                .with_for_update()
            )
            attempt = await session.scalar(
                select(GradingAttempt)
                .where(GradingAttempt.id == claim.attempt_id)
                .with_for_update()
            )
            if (
                job is None
                or item is None
                or attempt is None
                or attempt.status != "running"
                or item.status != "running"
                or item.lease_token != claim.lease_token
            ):
                raise RuntimeError("评分 attempt 租约已失效")
            result = completion.validated_result
            provider_result = completion.provider_result
            attempt.status = "succeeded"
            attempt.provider_call_state = "response_received"
            attempt.provider_request_id = provider_result.request_id
            attempt.reported_model = provider_result.reported_model
            attempt.subtotal = result.subtotal
            attempt.deduction_total = result.deduction_total
            attempt.total_score = result.total_score
            attempt.criteria_results = [
                dimension.model_dump(mode="json") for dimension in result.dimensions
            ]
            attempt.deduction_results = [
                deduction.model_dump(mode="json") for deduction in result.deductions
            ]
            attempt.overall_feedback = result.overall_feedback
            attempt.raw_response_object_key = completion.response_object_key
            attempt.raw_response_sha256 = completion.response_object_sha256
            attempt.input_tokens = provider_result.usage.input_tokens
            attempt.cached_input_tokens = provider_result.usage.cached_input_tokens
            attempt.cache_write_input_tokens = provider_result.usage.cache_write_input_tokens
            attempt.output_tokens = provider_result.usage.output_tokens
            attempt.reasoning_tokens = provider_result.usage.reasoning_tokens
            attempt.total_tokens = provider_result.usage.total_tokens
            if provider_result.estimated_cost is not None:
                attempt.estimated_cost_amount = provider_result.estimated_cost.amount
                attempt.cost_currency = provider_result.estimated_cost.currency
                attempt.tariff_version = provider_result.estimated_cost.tariff_version
            attempt.finished_at = now
            item.status = "needs_review"
            item.finished_at = now
            item.lease_token = None
            item.lease_expires_at = None
            item.error_code = None
            item.updated_at = now
            await session.flush()
            await self._reconcile_job(session, job, now)

    async def finish_failure(
        self,
        claim: GradingAttemptClaim,
        failure: GradingAttemptFailure,
    ) -> None:
        now = datetime.now(UTC)
        async with self._worker_session() as session:
            attempt_pointer = (
                await session.execute(
                    select(
                        GradingAttempt.grading_job_item_id,
                        GradingAttempt.owner_id,
                    ).where(GradingAttempt.id == claim.attempt_id)
                )
            ).one_or_none()
            if attempt_pointer is None:
                raise RuntimeError("评分 attempt 不存在")
            item_pointer = (
                await session.execute(
                    select(GradingJobItem.grading_job_id).where(
                        GradingJobItem.id == attempt_pointer.grading_job_item_id,
                        GradingJobItem.owner_id == attempt_pointer.owner_id,
                    )
                )
            ).scalar_one()
            job = await session.scalar(
                select(GradingJob).where(GradingJob.id == item_pointer).with_for_update()
            )
            item = await session.scalar(
                select(GradingJobItem)
                .where(GradingJobItem.id == attempt_pointer.grading_job_item_id)
                .with_for_update()
            )
            attempt = await session.scalar(
                select(GradingAttempt)
                .where(GradingAttempt.id == claim.attempt_id)
                .with_for_update()
            )
            if (
                job is None
                or item is None
                or attempt is None
                or attempt.status != "running"
                or item.status != "running"
                or item.lease_token != claim.lease_token
            ):
                raise RuntimeError("评分 attempt 租约已失效")
            attempt.status = "failed"
            attempt.provider_call_state = failure.provider_call_state
            attempt.error_code = failure.error_code
            attempt.error_details = failure.error_details
            attempt.finished_at = now
            if failure.provider_result is not None:
                provider_result = failure.provider_result
                attempt.provider_request_id = provider_result.request_id
                attempt.reported_model = provider_result.reported_model
                attempt.input_tokens = provider_result.usage.input_tokens
                attempt.cached_input_tokens = provider_result.usage.cached_input_tokens
                attempt.cache_write_input_tokens = provider_result.usage.cache_write_input_tokens
                attempt.output_tokens = provider_result.usage.output_tokens
                attempt.reasoning_tokens = provider_result.usage.reasoning_tokens
                attempt.total_tokens = provider_result.usage.total_tokens
                if provider_result.estimated_cost is not None:
                    attempt.estimated_cost_amount = provider_result.estimated_cost.amount
                    attempt.cost_currency = provider_result.estimated_cost.currency
                    attempt.tariff_version = provider_result.estimated_cost.tariff_version
            elif failure.provider_request_id is not None:
                attempt.provider_request_id = failure.provider_request_id
            attempt.raw_response_object_key = failure.response_object_key
            attempt.raw_response_sha256 = failure.response_object_sha256
            item.lease_token = None
            item.lease_expires_at = None
            item.updated_at = now
            if failure.action == "retry":
                item.status = "queued"
                item.retry_count += 1
                item.available_at = now + timedelta(seconds=failure.retry_delay_seconds)
                item.finished_at = None
                item.error_code = None
            elif failure.action == "needs_review":
                item.status = "needs_review"
                item.finished_at = now
                item.error_code = failure.error_code
            else:
                item.status = "failed"
                item.finished_at = now
                item.error_code = failure.error_code
            await session.flush()
            await self._reconcile_job(session, job, now)

    @staticmethod
    async def _reconcile_job(
        session: AsyncSession,
        job: GradingJob,
        now: datetime,
    ) -> None:
        statuses = list(
            (
                await session.scalars(
                    select(GradingJobItem.status).where(GradingJobItem.grading_job_id == job.id)
                )
            ).all()
        )
        if len(statuses) != job.expected_item_count:
            raise RuntimeError("评分批次论文数量与快照不一致")
        counts = Counter(statuses)
        if job.status != "cancelled" and counts["queued"] == 0 and counts["running"] == 0:
            if counts["needs_review"] or counts["completed"]:
                job.status = "needs_review"
                job.finished_at = None
            elif counts["failed"]:
                job.status = "failed"
                job.finished_at = now
            else:
                job.status = "cancelled"
                job.finished_at = now
        job.state_version += 1
        job.updated_at = now
        await session.flush()
