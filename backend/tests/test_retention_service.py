"""阶段十三保留清理公开状态机行为。"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from app.maintenance.retention import (
    RetentionCandidate,
    RetentionClaim,
    RetentionCloseError,
    RetentionRevalidation,
    RetentionRunResult,
    RetentionService,
    RetentionStorageTimeout,
    StorageDeleteResult,
)

CANDIDATE_ID = UUID("11111111-1111-4111-8111-111111111111")
LEASE_TOKEN = UUID("22222222-2222-4222-8222-222222222222")


class Repository:
    def __init__(
        self,
        *,
        close_errors: int = 0,
        revalidation: RetentionRevalidation = "eligible",
        complete: bool = True,
        claim: bool = True,
        fail: bool = True,
        returned_token: UUID = LEASE_TOKEN,
    ) -> None:
        self.previewed = False
        self.close_errors = close_errors
        self.revalidation = revalidation
        self.should_complete = complete
        self.should_claim = claim
        self.should_fail = fail
        self.returned_token = returned_token
        self.claims: list[tuple[UUID, int]] = []
        self.completed: list[tuple[UUID, UUID, StorageDeleteResult]] = []
        self.failed: list[tuple[UUID, UUID, str]] = []

    async def list_candidates(self, *, limit: int) -> tuple[RetentionCandidate, ...]:
        self.previewed = True
        assert limit == 25
        return (
            RetentionCandidate(
                id=CANDIDATE_ID,
                object_class="submission_source",
                object_key="private/source.pdf",
                eligible_at=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        )

    async def claim_next(
        self,
        lease_token: UUID,
        *,
        lease_seconds: int,
    ) -> RetentionClaim | None:
        self.claims.append((lease_token, lease_seconds))
        if not self.should_claim:
            return None
        return RetentionClaim(
            candidate=(await self.list_candidates(limit=25))[0],
            lease_token=self.returned_token,
        )

    async def revalidate_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
    ) -> RetentionRevalidation:
        assert candidate_id == CANDIDATE_ID
        assert lease_token == LEASE_TOKEN
        return self.revalidation

    async def complete_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
        storage_result: StorageDeleteResult,
    ) -> bool:
        if self.close_errors:
            self.close_errors -= 1
            raise RetentionCloseError("database unavailable")
        if not self.should_complete:
            return False
        self.completed.append((candidate_id, lease_token, storage_result))
        return True

    async def fail_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
        error_code: str,
    ) -> bool:
        if not self.should_fail:
            return False
        self.failed.append((candidate_id, lease_token, error_code))
        return True


class Storage:
    def __init__(
        self,
        *,
        result: StorageDeleteResult = "deleted",
        results: list[StorageDeleteResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.results = results
        self.error = error
        self.deleted: list[str] = []

    async def delete(self, object_key: str) -> StorageDeleteResult:
        self.deleted.append(object_key)
        if self.error is not None:
            raise self.error
        if self.results is not None:
            return self.results.pop(0)
        return self.result


def test_dry_run_returns_read_only_candidates() -> None:
    repository = Repository()
    service = RetentionService(repository=repository, storage=Storage())

    candidates = asyncio.run(service.preview(limit=25))

    assert candidates[0].id == CANDIDATE_ID
    assert repository.previewed is True


def test_automatic_deletion_is_disabled_by_default() -> None:
    service = RetentionService(repository=Repository(), storage=Storage())

    result = asyncio.run(service.run_once())

    assert result == RetentionRunResult(status="disabled")


def test_enabled_run_claims_with_a_lease_revalidates_then_deletes_and_closes() -> None:
    repository = Repository()
    storage = Storage()
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="deleted", candidate_id=CANDIDATE_ID)
    assert repository.claims == [(LEASE_TOKEN, 120)]
    assert storage.deleted == ["private/source.pdf"]
    assert repository.completed == [(CANDIDATE_ID, LEASE_TOKEN, "deleted")]


def test_storage_missing_is_closed_as_an_idempotent_success() -> None:
    repository = Repository()
    service = RetentionService(
        repository=repository,
        storage=Storage(result="missing"),
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="already_missing", candidate_id=CANDIDATE_ID)
    assert repository.completed == [(CANDIDATE_ID, LEASE_TOKEN, "missing")]


def test_storage_timeout_enters_an_explicit_retryable_failure() -> None:
    repository = Repository()
    service = RetentionService(
        repository=repository,
        storage=Storage(error=RetentionStorageTimeout("timed out")),
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="storage_timeout", candidate_id=CANDIDATE_ID)
    assert repository.failed == [(CANDIDATE_ID, LEASE_TOKEN, "retention_storage_timeout")]
    assert repository.completed == []


def test_database_close_failure_after_delete_is_safe_to_redeliver() -> None:
    repository = Repository(close_errors=1)
    storage = Storage(results=["deleted", "missing"])
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    first = asyncio.run(service.run_once(automatic_delete=True))
    second = asyncio.run(service.run_once(automatic_delete=True))

    assert first == RetentionRunResult(status="close_failed", candidate_id=CANDIDATE_ID)
    assert second == RetentionRunResult(status="already_missing", candidate_id=CANDIDATE_ID)
    assert repository.failed == []
    assert repository.completed == [(CANDIDATE_ID, LEASE_TOKEN, "missing")]


def test_lost_lease_during_revalidation_never_deletes_or_closes() -> None:
    repository = Repository(revalidation="lease_lost")
    storage = Storage()
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="lease_lost", candidate_id=CANDIDATE_ID)
    assert storage.deleted == []
    assert repository.completed == []
    assert repository.failed == []


def test_lost_lease_after_delete_does_not_write_a_stale_completion() -> None:
    repository = Repository(complete=False)
    storage = Storage()
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="lease_lost", candidate_id=CANDIDATE_ID)
    assert storage.deleted == ["private/source.pdf"]
    assert repository.completed == []
    assert repository.failed == []


def test_stale_candidate_is_invalidated_before_storage_delete() -> None:
    repository = Repository(revalidation="ineligible")
    storage = Storage()
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="invalidated", candidate_id=CANDIDATE_ID)
    assert storage.deleted == []
    assert repository.completed == []
    assert repository.failed == []


def test_enabled_run_is_idle_when_no_candidate_can_be_claimed() -> None:
    repository = Repository(claim=False)
    storage = Storage()
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="idle")
    assert storage.deleted == []


def test_timeout_does_not_write_failure_after_the_lease_is_lost() -> None:
    repository = Repository(fail=False)
    service = RetentionService(
        repository=repository,
        storage=Storage(error=RetentionStorageTimeout("timed out")),
        token_factory=lambda: LEASE_TOKEN,
    )

    result = asyncio.run(service.run_once(automatic_delete=True))

    assert result == RetentionRunResult(status="lease_lost", candidate_id=CANDIDATE_ID)
    assert repository.failed == []
    assert repository.completed == []


def test_mismatched_claim_token_is_rejected_before_storage_delete() -> None:
    repository = Repository(returned_token=UUID("33333333-3333-4333-8333-333333333333"))
    storage = Storage()
    service = RetentionService(
        repository=repository,
        storage=storage,
        token_factory=lambda: LEASE_TOKEN,
    )

    try:
        asyncio.run(service.run_once(automatic_delete=True))
    except RuntimeError as error:
        assert str(error) == "保留候选领取令牌不一致"
    else:
        raise AssertionError("不一致的领取令牌必须失败")

    assert storage.deleted == []
