"""阶段十三配额函数的 PostgreSQL 仓储边界。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database

QuotaGateState = Literal["ok", "warning"]
StorageFinalState = Literal["committed", "released", "uncertain"]


@dataclass(frozen=True, slots=True)
class QuotaGateResult:
    """一次数据库函数配额判断的安全投影。"""

    state: QuotaGateState
    resource: str
    reservation_id: UUID | None
    used_bytes: int
    reserved_bytes: int
    requested_bytes: int
    capacity_bytes: int | None

    @property
    def projected_bytes(self) -> int:
        return self.used_bytes + self.reserved_bytes + self.requested_bytes


class QuotaExceededError(RuntimeError):
    """增长操作达到硬限制。"""

    def __init__(self, *, resource: str, code: str) -> None:
        super().__init__(code)
        self.resource = resource
        self.code = code


class QuotaUnavailableError(RuntimeError):
    """配额状态未知、过期或采样失败，不能可靠判断。"""

    def __init__(self, *, resource: str, code: str) -> None:
        super().__init__(code)
        self.resource = resource
        self.code = code


class SqlAlchemyQuotaRepository:
    """只调用迁移提供的最小权限函数，不直接读写配额表。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def check_database_growth(
        self,
        session: AsyncSession,
        *,
        operation_key: str,
        requested_bytes: int,
    ) -> QuotaGateResult:
        """在调用方批次事务中执行数据库增长门禁。"""

        self._validate_request(operation_key, requested_bytes)
        result = await session.execute(
            text(
                "select * from paper_grading_private.check_database_growth("
                ":operation_key, :requested_bytes)"
            ),
            {
                "operation_key": operation_key,
                "requested_bytes": requested_bytes,
            },
        )
        return self._parse_result(cast(Mapping[str, object], result.mappings().one()))

    async def reserve_storage_growth(
        self,
        *,
        operation_key: str,
        object_key: str,
        content_sha256: bytes,
        requested_bytes: int,
    ) -> QuotaGateResult:
        """在外部对象写入前，用精确对象身份原子预留 Storage 字节。"""

        self._validate_request(operation_key, requested_bytes)
        if not object_key.strip():
            raise ValueError("Storage 对象键不能为空")
        if len(content_sha256) != 32:
            raise ValueError("Storage 内容哈希必须是 32 字节")
        async with self._database.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "select * from paper_grading_private.reserve_storage_growth("
                    ":operation_key, :object_key, :content_sha256, :requested_bytes)"
                ),
                {
                    "operation_key": operation_key,
                    "object_key": object_key,
                    "content_sha256": content_sha256,
                    "requested_bytes": requested_bytes,
                },
            )
            return self._parse_result(cast(Mapping[str, object], result.mappings().one()))

    async def commit_storage_growth(self, reservation_id: UUID) -> QuotaGateResult:
        """确认对象写入成功，并保留字节直到新样本覆盖它。"""

        return await self._finalize_storage_growth(reservation_id, "committed")

    async def release_storage_growth(self, reservation_id: UUID) -> QuotaGateResult:
        """确认对象未增长，立即释放预留。"""

        return await self._finalize_storage_growth(reservation_id, "released")

    async def mark_storage_growth_uncertain(self, reservation_id: UUID) -> QuotaGateResult:
        """远端结果不确定时继续计入预留，等待后续对账。"""

        return await self._finalize_storage_growth(reservation_id, "uncertain")

    async def _finalize_storage_growth(
        self,
        reservation_id: UUID,
        target_state: StorageFinalState,
    ) -> QuotaGateResult:
        async with self._database.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "select * from paper_grading_private.finalize_storage_growth("
                    ":reservation_id, :target_state)"
                ),
                {
                    "reservation_id": reservation_id,
                    "target_state": target_state,
                },
            )
            return self._parse_result(cast(Mapping[str, object], result.mappings().one()))

    @staticmethod
    def _validate_request(operation_key: str, requested_bytes: int) -> None:
        if not operation_key.strip():
            raise ValueError("配额操作键不能为空")
        if requested_bytes < 0:
            raise ValueError("配额请求字节数不能为负数")

    @staticmethod
    def _parse_result(row: Mapping[str, object]) -> QuotaGateResult:
        try:
            state = row["state"]
            resource = row["resource"]
            reservation_id = row["reservation_id"]
            used_bytes = row["used_bytes"]
            reserved_bytes = row["reserved_bytes"]
            requested_bytes = row["requested_bytes"]
            capacity_bytes = row["capacity_bytes"]
            error_code = row["error_code"]
        except KeyError as error:
            raise RuntimeError("配额函数返回字段不完整") from error

        if not isinstance(state, str) or not isinstance(resource, str) or not resource:
            raise RuntimeError("配额函数返回状态无效")
        if reservation_id is not None and not isinstance(reservation_id, UUID):
            raise RuntimeError("配额函数返回预留标识无效")
        byte_values = (used_bytes, reserved_bytes, requested_bytes)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in byte_values
        ):
            raise RuntimeError("配额函数返回字节数无效")
        if capacity_bytes is not None and (
            isinstance(capacity_bytes, bool)
            or not isinstance(capacity_bytes, int)
            or capacity_bytes < 0
        ):
            raise RuntimeError("配额函数返回字节数无效")
        if error_code is not None and (not isinstance(error_code, str) or not error_code):
            raise RuntimeError("配额函数返回错误码无效")

        stable_code = (
            error_code
            if isinstance(error_code, str)
            else f"{resource}_quota_{'exceeded' if state == 'blocked' else 'unavailable'}"
        )
        if state == "blocked":
            raise QuotaExceededError(resource=resource, code=stable_code)
        if state == "unavailable":
            raise QuotaUnavailableError(resource=resource, code=stable_code)
        if state not in {"ok", "warning"}:
            raise RuntimeError("配额函数返回状态无效")
        return QuotaGateResult(
            state=cast(QuotaGateState, state),
            resource=resource,
            reservation_id=reservation_id,
            used_bytes=cast(int, used_bytes),
            reserved_bytes=cast(int, reserved_bytes),
            requested_bytes=cast(int, requested_bytes),
            capacity_bytes=capacity_bytes,
        )
