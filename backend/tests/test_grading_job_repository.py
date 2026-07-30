"""阶段十 PostgreSQL 仓储的公开行为回归。"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from app.db import Database
from app.monitoring.repository import QuotaExceededError
from app.workers.models import GradingJobCreate
from app.workers.repository import (
    GRADING_JOB_BASE_RESERVATION_BYTES,
    GRADING_JOB_ITEM_RESERVATION_BYTES,
    SqlAlchemyGradingJobRepository,
)

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
ASSIGNMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
ITEM_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("55555555-5555-5555-5555-555555555555")
RUBRIC_ID = UUID("66666666-6666-6666-6666-666666666666")


class ScalarRows:
    """模拟 SQLAlchemy ScalarResult。"""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class ChunkedTupleRows:
    """保留真实 ChunkedIteratorResult 的映射探测行为。"""

    def keys(self) -> tuple[str, str]:
        return ("grading_job_item_id", "count")

    def __iter__(self) -> Iterator[tuple[UUID, int]]:
        return iter(((ITEM_ID, 2),))


class ExecuteResult:
    def tuples(self) -> ChunkedTupleRows:
        return ChunkedTupleRows()


class FakeSession:
    def __init__(self) -> None:
        timestamp = datetime(2026, 7, 18, tzinfo=UTC)
        self.job = SimpleNamespace(
            id=JOB_ID,
            assignment_id=ASSIGNMENT_ID,
            rubric_version_id=RUBRIC_ID,
            model="deepseek-v4-pro",
            status="running",
            state_version=2,
            expected_item_count=1,
            started_at=timestamp,
            finished_at=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.item = SimpleNamespace(
            id=ITEM_ID,
            submission_id=SUBMISSION_ID,
            position=0,
            status="running",
            dispatch_version=1,
            error_code=None,
        )

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def scalar(self, _statement: object) -> object:
        return self.job

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows([self.item])

    async def execute(self, statement: object, _parameters: object = None) -> object:
        if statement.__class__.__name__ == "TextClause":
            return object()
        return ExecuteResult()


class FakeSessions:
    def __init__(self, session: object) -> None:
        self._session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[object]:
        yield self._session


def test_teacher_reads_attempt_count_from_chunked_sqlalchemy_rows() -> None:
    """教师读取批次时，真实分块结果不能被误当成映射。"""

    session = FakeSession()
    database = SimpleNamespace(sessions=FakeSessions(session))
    repository = SqlAlchemyGradingJobRepository(cast(Database, database))

    job = asyncio.run(repository.get_job(OWNER_ID, JOB_ID))

    assert job is not None
    assert job.items[0].attempt_count == 2


class QuotaBlockingSession:
    def __init__(self) -> None:
        self.scalar_calls = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def execute(self, _statement: object, _parameters: object = None) -> object:
        return object()

    async def scalar(self, _statement: object) -> object:
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return None
        raise AssertionError("数据库配额阻断后不应继续读取或写入批次")


class BlockingQuota:
    def __init__(self) -> None:
        self.operation_key = ""

    async def check_database_growth(
        self,
        _session: object,
        *,
        operation_key: str,
        requested_bytes: int,
    ) -> None:
        self.operation_key = operation_key
        assert requested_bytes == (
            GRADING_JOB_BASE_RESERVATION_BYTES + GRADING_JOB_ITEM_RESERVATION_BYTES
        )
        raise QuotaExceededError(resource="database", code="database_quota_exceeded")


def test_new_grading_job_checks_database_quota_inside_the_creation_transaction() -> None:
    session = QuotaBlockingSession()
    quota = BlockingQuota()
    database = SimpleNamespace(sessions=FakeSessions(session))
    repository = SqlAlchemyGradingJobRepository(
        cast(Database, database),
        quota=quota,  # type: ignore[arg-type]
    )

    with pytest.raises(QuotaExceededError, match="database_quota_exceeded"):
        asyncio.run(
            repository.create_or_get_job(
                OWNER_ID,
                ASSIGNMENT_ID,
                GradingJobCreate(
                    submission_ids=(SUBMISSION_ID,),
                    idempotency_key="quota-gated-request",
                ),
            )
        )

    assert quota.operation_key == f"grading-job:{OWNER_ID}:quota-gated-request"
    assert session.scalar_calls == 1
