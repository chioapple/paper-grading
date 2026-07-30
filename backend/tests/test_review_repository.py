"""阶段十一复核仓储的公开行为回归。"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError

from app.db import Database
from app.reviews.models import ReviewDraftData
from app.reviews.repository import SqlAlchemyReviewRepository
from app.reviews.service import ReviewConflictError, ReviewValidationError

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
ASSIGNMENT_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
ITEM_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("55555555-5555-5555-5555-555555555555")
JOB_TWO_ID = UUID("66666666-6666-6666-6666-666666666666")
ITEM_TWO_ID = UUID("77777777-7777-7777-7777-777777777777")
SUBMISSION_TWO_ID = UUID("88888888-8888-8888-8888-888888888888")
DRAFT_DATA = ReviewDraftData.model_construct(
    attempt_id=UUID("99999999-9999-9999-9999-999999999999"),
    criteria=(),
    deductions=(),
    evidence=(),
    overall_feedback="Test feedback",
    change_reason=None,
    subtotal=Decimal("1"),
    deduction_total=Decimal("0"),
    final_score=Decimal("1"),
)


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


class RowResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self._rows

    def scalars(self) -> ScalarRows:
        return ScalarRows([row[0] for row in self._rows])


class AttemptCountResult:
    def tuples(self) -> ChunkedTupleRows:
        return ChunkedTupleRows()


class FakeSession:
    def __init__(self) -> None:
        timestamp = datetime(2026, 7, 20, tzinfo=UTC)
        self.job = SimpleNamespace(
            id=JOB_ID,
            assignment_id=ASSIGNMENT_ID,
            assignment_title_snapshot="Test",
            model="deepseek-v4-pro",
            status="needs_review",
            expected_item_count=1,
            created_at=timestamp,
            finished_at=None,
        )
        self.item = SimpleNamespace(
            id=ITEM_ID,
            grading_job_id=JOB_ID,
            position=0,
            status="needs_review",
            error_code=None,
        )
        self.submission = SimpleNamespace(
            id=SUBMISSION_ID,
            original_filename="paper.pdf",
        )
        self._select_number = 0

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows([self.job])

    async def execute(self, statement: object, _parameters: object = None) -> object:
        if statement.__class__.__name__ == "TextClause":
            return object()
        self._select_number += 1
        if self._select_number == 1:
            return RowResult([(self.item, self.submission)])
        if self._select_number == 2:
            return AttemptCountResult()
        if self._select_number == 3:
            return RowResult([(ITEM_ID,)])
        return RowResult([])


class FakeSessions:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[FakeSession]:
        yield self._session


class SqlStateError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


class FailingSession(FakeSession):
    def __init__(self, error: DBAPIError) -> None:
        super().__init__()
        self._error = error

    async def execute(self, _statement: object, _parameters: object = None) -> object:
        return object()

    async def scalar(self, _statement: object, _parameters: object = None) -> object:
        raise self._error


@pytest.mark.parametrize("sqlstate", ["08006", "42501", "42601"])
def test_save_draft_preserves_non_business_database_errors(sqlstate: str) -> None:
    database_error = DBAPIError(
        "select set_config(...) ",
        {},
        SqlStateError(sqlstate),
        connection_invalidated=sqlstate == "08006",
    )
    database = SimpleNamespace(sessions=FakeSessions(FailingSession(database_error)))
    repository = SqlAlchemyReviewRepository(cast(Database, database))

    with pytest.raises(DBAPIError) as captured:
        asyncio.run(
            repository.save_draft(
                OWNER_ID,
                ITEM_ID,
                DRAFT_DATA,
            )
        )

    assert captured.value is database_error


@pytest.mark.parametrize("sqlstate", ["23503", "23505", "23P01", "40001"])
def test_save_draft_maps_known_database_conflicts(sqlstate: str) -> None:
    database_error = DBAPIError("select review_function()", {}, SqlStateError(sqlstate))
    database = SimpleNamespace(sessions=FakeSessions(FailingSession(database_error)))
    repository = SqlAlchemyReviewRepository(cast(Database, database))

    with pytest.raises(ReviewConflictError) as captured:
        asyncio.run(
            repository.save_draft(
                OWNER_ID,
                ITEM_ID,
                DRAFT_DATA,
            )
        )

    assert captured.value.__cause__ is database_error


def test_save_draft_maps_check_violation_to_validation_error() -> None:
    database_error = DBAPIError("select review_function()", {}, SqlStateError("23514"))
    database = SimpleNamespace(sessions=FakeSessions(FailingSession(database_error)))
    repository = SqlAlchemyReviewRepository(cast(Database, database))

    with pytest.raises(ReviewValidationError) as captured:
        asyncio.run(
            repository.save_draft(
                OWNER_ID,
                ITEM_ID,
                DRAFT_DATA,
            )
        )

    assert captured.value.code == "review_database_validation_failed"


def test_teacher_lists_non_empty_jobs_from_chunked_sqlalchemy_rows() -> None:
    """真实分块计数结果不能使含论文的批次列表返回 500。"""

    session = FakeSession()
    database = SimpleNamespace(sessions=FakeSessions(session))
    repository = SqlAlchemyReviewRepository(cast(Database, database))

    jobs = asyncio.run(repository.list_jobs(OWNER_ID))

    assert len(jobs) == 1
    assert jobs[0].items[0].attempt_count == 2
    assert jobs[0].items[0].error_code is None
    assert jobs[0].items[0].review_available is True


def test_teacher_queue_marks_failed_only_attempt_as_unavailable_for_review() -> None:
    session = FakeSession()

    async def execute_without_success(statement: object, _parameters: object = None) -> object:
        if statement.__class__.__name__ == "TextClause":
            return object()
        session._select_number += 1
        if session._select_number == 1:
            return RowResult([(session.item, session.submission)])
        if session._select_number == 2:
            return AttemptCountResult()
        return RowResult([])

    session.execute = execute_without_success  # type: ignore[method-assign]
    database = SimpleNamespace(sessions=FakeSessions(session))
    repository = SqlAlchemyReviewRepository(cast(Database, database))

    jobs = asyncio.run(repository.list_jobs(OWNER_ID))

    assert jobs[0].items[0].review_available is False


class MultiJobSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.second_job = SimpleNamespace(
            **{
                **vars(self.job),
                "id": JOB_TWO_ID,
                "assignment_title_snapshot": "Test two",
            }
        )
        self.second_item = SimpleNamespace(
            id=ITEM_TWO_ID,
            grading_job_id=JOB_TWO_ID,
            position=0,
            status="needs_review",
            error_code=None,
        )
        self.second_submission = SimpleNamespace(
            id=SUBMISSION_TWO_ID,
            original_filename="paper-two.pdf",
        )

    async def scalars(self, _statement: object) -> ScalarRows:
        return ScalarRows([self.job, self.second_job])

    async def execute(self, statement: object, _parameters: object = None) -> object:
        if statement.__class__.__name__ == "TextClause":
            return object()
        self._select_number += 1
        if self._select_number == 1:
            return RowResult(
                [
                    (self.item, self.submission),
                    (self.second_item, self.second_submission),
                ]
            )
        if self._select_number == 2:
            return AttemptCountResult()
        if self._select_number == 3:
            return RowResult([(ITEM_ID,)])
        return RowResult([])


def test_teacher_job_list_query_count_does_not_grow_per_job() -> None:
    """批次数量增加时仍只执行固定数量的集合查询。"""

    session = MultiJobSession()
    database = SimpleNamespace(sessions=FakeSessions(session))
    repository = SqlAlchemyReviewRepository(cast(Database, database))

    jobs = asyncio.run(repository.list_jobs(OWNER_ID))

    assert [item.id for item in jobs] == [JOB_ID, JOB_TWO_ID]
    assert session._select_number == 4
