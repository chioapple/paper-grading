"""阶段十三保留仓储的公开行为测试。"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from app.maintenance.retention_repository import SqlAlchemyRetentionRepository

CANDIDATE_ID = UUID("11111111-1111-4111-8111-111111111111")
LEASE_TOKEN = UUID("22222222-2222-4222-8222-222222222222")


class MappingRows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def __iter__(self) -> Iterator[dict[str, object]]:
        return iter(self._rows)

    def one(self) -> dict[str, object]:
        assert len(self._rows) == 1
        return self._rows[0]

    def one_or_none(self) -> dict[str, object] | None:
        assert len(self._rows) <= 1
        return self._rows[0] if self._rows else None


class ExecuteResult:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        scalar: object | None = None,
    ) -> None:
        self._rows = rows
        self._scalar = scalar

    def mappings(self) -> MappingRows:
        return MappingRows(self._rows)

    def scalar_one(self) -> object:
        return self._scalar


class RecordingSession:
    def __init__(self, results: list[ExecuteResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object],
    ) -> ExecuteResult:
        self.calls.append((str(statement), parameters))
        return self.results.pop(0)

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


class RecordingDatabase:
    def __init__(self, session: RecordingSession) -> None:
        self.session = session

    @asynccontextmanager
    async def sessions(self) -> AsyncIterator[RecordingSession]:
        yield self.session


def candidate_row() -> dict[str, object]:
    return {
        "id": CANDIDATE_ID,
        "object_class": "submission_source",
        "object_key": "teachers/owner/source.pdf",
        "eligible_at": datetime(2026, 7, 1, tzinfo=UTC),
    }


def test_preview_uses_the_read_only_candidate_function() -> None:
    session = RecordingSession([ExecuteResult([candidate_row()])])
    repository = SqlAlchemyRetentionRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    candidates = asyncio.run(repository.list_candidates(limit=25))

    assert candidates[0].id == CANDIDATE_ID
    assert "list_retention_candidates" in session.calls[0][0]
    assert session.calls[0][1] == {"limit": 25}


def test_claim_and_revalidation_use_database_owned_lease_state() -> None:
    row = {**candidate_row(), "lease_token": LEASE_TOKEN}
    session = RecordingSession(
        [
            ExecuteResult([row]),
            ExecuteResult([], scalar="eligible"),
        ]
    )
    repository = SqlAlchemyRetentionRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    claim = asyncio.run(repository.claim_next(LEASE_TOKEN, lease_seconds=120))
    state = asyncio.run(repository.revalidate_claim(CANDIDATE_ID, LEASE_TOKEN))

    assert claim is not None
    assert claim.lease_token == LEASE_TOKEN
    assert state == "eligible"
    assert "claim_next_retention_object" in session.calls[0][0]
    assert "revalidate_retention_object" in session.calls[1][0]


def test_storage_result_is_persisted_only_with_the_current_lease() -> None:
    session = RecordingSession([ExecuteResult([{"id": CANDIDATE_ID}])])
    repository = SqlAlchemyRetentionRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    completed = asyncio.run(repository.complete_claim(CANDIDATE_ID, LEASE_TOKEN, "missing"))

    assert completed is True
    assert session.calls[0][1] == {
        "candidate_id": CANDIDATE_ID,
        "lease_token": LEASE_TOKEN,
        "storage_result": "missing",
    }


def test_lost_lease_returns_false_instead_of_closing_another_worker() -> None:
    session = RecordingSession([ExecuteResult([{"id": None}])])
    repository = SqlAlchemyRetentionRepository(RecordingDatabase(session))  # type: ignore[arg-type]

    completed = asyncio.run(repository.complete_claim(CANDIDATE_ID, LEASE_TOKEN, "deleted"))

    assert completed is False
