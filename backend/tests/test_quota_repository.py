"""阶段十三配额仓储公开行为测试。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from app.monitoring.repository import (
    QuotaExceededError,
    QuotaUnavailableError,
    SqlAlchemyQuotaRepository,
)

RESERVATION_ID = UUID("11111111-1111-4111-8111-111111111111")


class MappingRows:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def one(self) -> dict[str, object]:
        return self._row


class ExecuteResult:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def mappings(self) -> MappingRows:
        return MappingRows(self._row)


class RecordingSession:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object],
    ) -> ExecuteResult:
        self.calls.append((str(statement), parameters))
        return ExecuteResult(self.row)

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


class RecordingDatabase:
    def __init__(self, session: RecordingSession) -> None:
        self.session = session
        self.transaction_count = 0

    @asynccontextmanager
    async def sessions(self) -> AsyncIterator[RecordingSession]:
        self.transaction_count += 1
        yield self.session


def quota_row(
    *,
    state: str = "ok",
    resource: str = "database",
    reservation_id: UUID | None = None,
    error_code: str | None = None,
    capacity_bytes: int | None = 1_000,
) -> dict[str, object]:
    return {
        "state": state,
        "resource": resource,
        "reservation_id": reservation_id,
        "used_bytes": 700,
        "reserved_bytes": 10,
        "requested_bytes": 20,
        "capacity_bytes": capacity_bytes,
        "error_code": error_code,
    }


def test_database_growth_check_uses_the_callers_open_transaction() -> None:
    session = RecordingSession(quota_row(state="warning"))
    database = RecordingDatabase(RecordingSession(quota_row()))
    repository = SqlAlchemyQuotaRepository(database)  # type: ignore[arg-type]

    result = asyncio.run(
        repository.check_database_growth(
            session,  # type: ignore[arg-type]
            operation_key="grading-job:owner:idempotency-key",
            requested_bytes=20,
        )
    )

    assert result.state == "warning"
    assert result.projected_bytes == 730
    assert database.transaction_count == 0
    assert session.calls[0][1] == {
        "operation_key": "grading-job:owner:idempotency-key",
        "requested_bytes": 20,
    }


def test_storage_growth_reservation_uses_object_identity_and_a_short_transaction() -> None:
    session = RecordingSession(
        quota_row(
            state="ok",
            resource="storage",
            reservation_id=RESERVATION_ID,
        )
    )
    database = RecordingDatabase(session)
    repository = SqlAlchemyQuotaRepository(database)  # type: ignore[arg-type]
    content_sha256 = bytes.fromhex("12" * 32)

    result = asyncio.run(
        repository.reserve_storage_growth(
            operation_key="submission-source:77777777",
            object_key="teachers/owner/assignments/assignment/submissions/id/source.pdf",
            content_sha256=content_sha256,
            requested_bytes=20,
        )
    )

    assert result.reservation_id == RESERVATION_ID
    assert result.resource == "storage"
    assert database.transaction_count == 1
    assert session.calls[0][1] == {
        "operation_key": "submission-source:77777777",
        "object_key": "teachers/owner/assignments/assignment/submissions/id/source.pdf",
        "content_sha256": content_sha256,
        "requested_bytes": 20,
    }


def test_hard_limit_is_exposed_as_a_stable_quota_error() -> None:
    session = RecordingSession(
        quota_row(
            state="blocked",
            resource="storage",
            error_code="storage_quota_exceeded",
        )
    )
    repository = SqlAlchemyQuotaRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(QuotaExceededError) as error:
        asyncio.run(
            repository.reserve_storage_growth(
                operation_key="submission-source:blocked",
                object_key="teachers/owner/source.pdf",
                content_sha256=bytes.fromhex("34" * 32),
                requested_bytes=20,
            )
        )

    assert error.value.code == "storage_quota_exceeded"
    assert error.value.resource == "storage"


def test_failed_or_stale_sample_is_not_treated_as_zero_usage() -> None:
    session = RecordingSession(
        quota_row(
            state="unavailable",
            resource="database",
            error_code="database_quota_sample_stale",
        )
    )
    repository = SqlAlchemyQuotaRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(QuotaUnavailableError) as error:
        asyncio.run(
            repository.check_database_growth(
                session,  # type: ignore[arg-type]
                operation_key="grading-job:stale-sample",
                requested_bytes=20,
            )
        )

    assert error.value.code == "database_quota_sample_stale"
    assert error.value.resource == "database"


def test_storage_sample_failure_is_not_treated_as_zero_usage() -> None:
    session = RecordingSession(
        quota_row(
            state="unavailable",
            resource="storage",
            error_code="storage_usage_unavailable",
        )
    )
    repository = SqlAlchemyQuotaRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(QuotaUnavailableError) as error:
        asyncio.run(
            repository.reserve_storage_growth(
                operation_key="submission-source:sample-unavailable",
                object_key="teachers/owner/source.pdf",
                content_sha256=bytes.fromhex("56" * 32),
                requested_bytes=20,
            )
        )

    assert error.value.code == "storage_usage_unavailable"
    assert error.value.resource == "storage"


@pytest.mark.parametrize(
    ("method_name", "target_state"),
    (
        ("commit_storage_growth", "committed"),
        ("release_storage_growth", "released"),
        ("mark_storage_growth_uncertain", "uncertain"),
    ),
)
def test_storage_reservation_has_explicit_terminal_and_uncertain_transitions(
    method_name: str,
    target_state: str,
) -> None:
    session = RecordingSession(
        quota_row(
            state="ok",
            resource="storage",
            reservation_id=RESERVATION_ID,
        )
    )
    database = RecordingDatabase(session)
    repository = SqlAlchemyQuotaRepository(database)  # type: ignore[arg-type]

    result = asyncio.run(getattr(repository, method_name)(RESERVATION_ID))

    assert result.reservation_id == RESERVATION_ID
    assert database.transaction_count == 1
    assert session.calls[0][1] == {
        "reservation_id": RESERVATION_ID,
        "target_state": target_state,
    }


def test_disabled_quota_accepts_growth_without_inventing_capacity_or_a_reservation() -> None:
    session = RecordingSession(quota_row(state="ok", capacity_bytes=None))
    repository = SqlAlchemyQuotaRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    result = asyncio.run(
        repository.check_database_growth(
            session,  # type: ignore[arg-type]
            operation_key="grading-job:quota-disabled",
            requested_bytes=20,
        )
    )

    assert result.state == "ok"
    assert result.capacity_bytes is None
    assert result.reservation_id is None


def test_malformed_database_result_crashes_instead_of_silently_allowing_growth() -> None:
    session = RecordingSession({"state": "ok"})
    repository = SqlAlchemyQuotaRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="字段不完整"):
        asyncio.run(
            repository.check_database_growth(
                session,  # type: ignore[arg-type]
                operation_key="grading-job:malformed-result",
                requested_bytes=20,
            )
        )
