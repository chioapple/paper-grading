"""供应商无关的保留清理状态机。"""

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

RetentionObjectClass = Literal[
    "submission_source",
    "submission_extracted",
    "grading_raw_response",
]
RetentionRunStatus = Literal[
    "disabled",
    "deleted",
    "already_missing",
    "storage_timeout",
    "close_failed",
    "lease_lost",
    "invalidated",
    "idle",
]
RetentionRevalidation = Literal["eligible", "ineligible", "lease_lost"]
StorageDeleteResult = Literal["deleted", "missing"]
RETENTION_LEASE_SECONDS = 120


class RetentionCandidate(BaseModel):
    """只读候选清单中的一个私有对象。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    object_class: RetentionObjectClass
    object_key: str = Field(min_length=1)
    eligible_at: datetime


class RetentionRunResult(BaseModel):
    """一次状态机投递的稳定结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RetentionRunStatus
    candidate_id: UUID | None = None


class RetentionClaim(BaseModel):
    """数据库领取成功后唯一允许删除对象的凭证。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: RetentionCandidate
    lease_token: UUID


class RetentionStorageTimeout(RuntimeError):
    """对象删除超时，远端结果可能未知。"""


class RetentionCloseError(RuntimeError):
    """对象结果已知，但数据库暂时无法持久化收口。"""


class RetentionRepository(Protocol):
    """保留状态的数据库边界。"""

    async def list_candidates(self, *, limit: int) -> tuple[RetentionCandidate, ...]: ...

    async def claim_next(
        self,
        lease_token: UUID,
        *,
        lease_seconds: int,
    ) -> RetentionClaim | None: ...

    async def revalidate_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
    ) -> RetentionRevalidation: ...

    async def complete_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
        storage_result: StorageDeleteResult,
    ) -> bool: ...

    async def fail_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
        error_code: str,
    ) -> bool: ...


class RetentionStorage(Protocol):
    """对象存储只暴露幂等删除，不泄露供应商响应。"""

    async def delete(self, object_key: str) -> StorageDeleteResult: ...


class RetentionService:
    """公开服务先提供不会写库或删对象的 dry-run。"""

    def __init__(
        self,
        *,
        repository: RetentionRepository,
        storage: RetentionStorage,
        token_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._token_factory = token_factory

    async def preview(self, *, limit: int = 100) -> tuple[RetentionCandidate, ...]:
        """只读返回数据库已经严格筛选的候选对象。"""

        if not 1 <= limit <= 1000:
            raise ValueError("保留候选数量必须在 1 到 1000 之间")
        return await self._repository.list_candidates(limit=limit)

    async def run_once(
        self,
        *,
        automatic_delete: bool = False,
    ) -> RetentionRunResult:
        """自动删除必须由每次调用显式开启。"""

        if not automatic_delete:
            return RetentionRunResult(status="disabled")
        lease_token = self._token_factory()
        claim = await self._repository.claim_next(
            lease_token,
            lease_seconds=RETENTION_LEASE_SECONDS,
        )
        if claim is None:
            return RetentionRunResult(status="idle")
        if claim.lease_token != lease_token:
            raise RuntimeError("保留候选领取令牌不一致")
        revalidation = await self._repository.revalidate_claim(
            claim.candidate.id,
            lease_token,
        )
        if revalidation == "lease_lost":
            return RetentionRunResult(
                status="lease_lost",
                candidate_id=claim.candidate.id,
            )
        if revalidation == "ineligible":
            return RetentionRunResult(
                status="invalidated",
                candidate_id=claim.candidate.id,
            )
        if revalidation != "eligible":
            raise RuntimeError("保留候选复核结果无效")
        try:
            storage_result = await self._storage.delete(claim.candidate.object_key)
        except RetentionStorageTimeout:
            failed = await self._repository.fail_claim(
                claim.candidate.id,
                lease_token,
                "retention_storage_timeout",
            )
            if not failed:
                return RetentionRunResult(
                    status="lease_lost",
                    candidate_id=claim.candidate.id,
                )
            return RetentionRunResult(
                status="storage_timeout",
                candidate_id=claim.candidate.id,
            )
        try:
            completed = await self._repository.complete_claim(
                claim.candidate.id,
                lease_token,
                storage_result,
            )
        except RetentionCloseError:
            return RetentionRunResult(
                status="close_failed",
                candidate_id=claim.candidate.id,
            )
        if not completed:
            return RetentionRunResult(
                status="lease_lost",
                candidate_id=claim.candidate.id,
            )
        return RetentionRunResult(
            status="deleted" if storage_result == "deleted" else "already_missing",
            candidate_id=claim.candidate.id,
        )
