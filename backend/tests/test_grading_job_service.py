"""阶段十批量评分服务的行为测试。"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.workers.models import (
    GradingJobCreate,
    GradingJobCreation,
    GradingJobItemView,
    GradingJobView,
)
from app.workers.service import GradingJobService

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
ASSIGNMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
ITEM_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("55555555-5555-5555-5555-555555555555")
RUBRIC_ID = UUID("66666666-6666-6666-6666-666666666666")


class CreateOnlyRepository:
    """创建测试不允许意外进入读取或控制路径。"""

    async def get_job(self, owner_id: UUID, job_id: UUID) -> GradingJobView | None:
        raise AssertionError((owner_id, job_id))

    async def control_job(
        self,
        owner_id: UUID,
        job_id: UUID,
        action: str,
        item_id: UUID | None = None,
    ) -> GradingJobView | None:
        raise AssertionError((owner_id, job_id, action, item_id))


def queued_job() -> GradingJobView:
    created_at = datetime(2026, 7, 16, tzinfo=UTC)
    return GradingJobView(
        id=JOB_ID,
        assignment_id=ASSIGNMENT_ID,
        rubric_version_id=RUBRIC_ID,
        model="deepseek-v4-pro",
        status="queued",
        state_version=1,
        total=1,
        queued=1,
        running=0,
        needs_review=0,
        completed=0,
        failed=0,
        cancelled=0,
        items=(
            GradingJobItemView(
                id=ITEM_ID,
                submission_id=SUBMISSION_ID,
                position=0,
                status="queued",
                attempt_count=0,
                error_code=None,
            ),
        ),
        started_at=None,
        finished_at=None,
        created_at=created_at,
        updated_at=created_at,
    )


def test_create_job_commits_the_batch_before_enqueuing_each_item() -> None:
    events: list[str] = []

    class Repository(CreateOnlyRepository):
        async def create_or_get_job(
            self,
            owner_id: UUID,
            assignment_id: UUID,
            payload: GradingJobCreate,
        ) -> GradingJobCreation:
            assert owner_id == OWNER_ID
            assert assignment_id == ASSIGNMENT_ID
            assert payload.submission_ids == (SUBMISSION_ID,)
            events.append("committed")
            return GradingJobCreation(job=queued_job(), created=True)

    class Queue:
        async def enqueue(self, item_id: UUID, dispatch_version: int) -> None:
            assert item_id == ITEM_ID
            assert dispatch_version == 1
            events.append("enqueued")

    service = GradingJobService(repository=Repository(), queue=Queue())

    result = asyncio.run(
        service.create_job(
            OWNER_ID,
            ASSIGNMENT_ID,
            GradingJobCreate(
                submission_ids=(SUBMISSION_ID,),
                idempotency_key="2026-07-16-class-a-first-pass",
            ),
        )
    )

    assert result == queued_job()
    assert events == ["committed", "enqueued"]


def test_one_hundred_submissions_are_dispatched_once_in_saved_position_order() -> None:
    base = queued_job()
    items = tuple(
        GradingJobItemView(
            id=UUID(int=1_000 + position),
            submission_id=UUID(int=2_000 + position),
            position=position,
            status="queued",
            attempt_count=0,
            error_code=None,
        )
        for position in range(100)
    )
    job = base.model_copy(
        update={
            "total": 100,
            "queued": 100,
            "items": items,
        }
    )

    class Repository(CreateOnlyRepository):
        async def create_or_get_job(
            self,
            owner_id: UUID,
            assignment_id: UUID,
            payload: GradingJobCreate,
        ) -> GradingJobCreation:
            assert len(payload.submission_ids) == 100
            return GradingJobCreation(job=job, created=True)

    dispatched: list[tuple[UUID, int]] = []

    class Queue:
        async def enqueue(self, item_id: UUID, dispatch_version: int) -> None:
            dispatched.append((item_id, dispatch_version))

    result = asyncio.run(
        GradingJobService(repository=Repository(), queue=Queue()).create_job(
            OWNER_ID,
            ASSIGNMENT_ID,
            GradingJobCreate(
                submission_ids=tuple(item.submission_id for item in items),
                idempotency_key="one-hundred-submissions",
            ),
        )
    )

    assert [item.position for item in result.items] == list(range(100))
    assert dispatched == [(item.id, 1) for item in items]
    assert len({item_id for item_id, _version in dispatched}) == 100
