"""阶段十三保留清理的最小权限 PostgreSQL 仓储。"""

from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import Database
from app.maintenance.retention import (
    RetentionCandidate,
    RetentionClaim,
    RetentionCloseError,
    RetentionObjectClass,
    RetentionRevalidation,
    StorageDeleteResult,
)


class SqlAlchemyRetentionRepository:
    """只调用 0018 的 SECURITY DEFINER 函数，不直接修改生命周期表。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _candidate(row: Mapping[str, object]) -> RetentionCandidate:
        candidate_id = row.get("id")
        object_class = row.get("object_class")
        object_key = row.get("object_key")
        eligible_at = row.get("eligible_at")
        if (
            not isinstance(candidate_id, UUID)
            or object_class
            not in {
                "submission_source",
                "submission_extracted",
                "grading_raw_response",
            }
            or not isinstance(object_key, str)
            or not object_key
            or not isinstance(eligible_at, datetime)
        ):
            raise RuntimeError("保留函数返回候选无效")
        return RetentionCandidate(
            id=candidate_id,
            object_class=cast(RetentionObjectClass, object_class),
            object_key=object_key,
            eligible_at=eligible_at,
        )

    async def list_candidates(self, *, limit: int) -> tuple[RetentionCandidate, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("保留候选数量必须在 1 到 1000 之间")
        async with self._database.sessions() as session, session.begin():
            rows = (
                await session.execute(
                    text("select * from paper_grading_private.list_retention_candidates(:limit)"),
                    {"limit": limit},
                )
            ).mappings()
            return tuple(self._candidate(cast(Mapping[str, object], row)) for row in rows)

    async def claim_next(
        self,
        lease_token: UUID,
        *,
        lease_seconds: int,
    ) -> RetentionClaim | None:
        async with self._database.sessions() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            "select * from paper_grading_private."
                            "claim_next_retention_object(:lease_token, :lease_seconds)"
                        ),
                        {
                            "lease_token": lease_token,
                            "lease_seconds": lease_seconds,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            returned_token = row.get("lease_token")
            if not isinstance(returned_token, UUID):
                raise RuntimeError("保留函数返回领取令牌无效")
            return RetentionClaim(
                candidate=self._candidate(cast(Mapping[str, object], row)),
                lease_token=returned_token,
            )

    async def revalidate_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
    ) -> RetentionRevalidation:
        async with self._database.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "select paper_grading_private."
                    "revalidate_retention_object(:candidate_id, :lease_token)"
                ),
                {
                    "candidate_id": candidate_id,
                    "lease_token": lease_token,
                },
            )
            state = result.scalar_one()
            if state not in {"eligible", "ineligible", "lease_lost"}:
                raise RuntimeError("保留函数返回复核状态无效")
            return cast(RetentionRevalidation, state)

    async def complete_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
        storage_result: StorageDeleteResult,
    ) -> bool:
        try:
            async with self._database.sessions() as session, session.begin():
                row = (
                    (
                        await session.execute(
                            text(
                                "select * from paper_grading_private."
                                "complete_retention_object("
                                ":candidate_id, :lease_token, :storage_result)"
                            ),
                            {
                                "candidate_id": candidate_id,
                                "lease_token": lease_token,
                                "storage_result": storage_result,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                return isinstance(row.get("id"), UUID)
        except SQLAlchemyError as error:
            raise RetentionCloseError("retention_database_close_failed") from error

    async def fail_claim(
        self,
        candidate_id: UUID,
        lease_token: UUID,
        error_code: str,
    ) -> bool:
        async with self._database.sessions() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            "select * from paper_grading_private."
                            "fail_retention_object("
                            ":candidate_id, :lease_token, :error_code)"
                        ),
                        {
                            "candidate_id": candidate_id,
                            "lease_token": lease_token,
                            "error_code": error_code,
                        },
                    )
                )
                .mappings()
                .one()
            )
            return isinstance(row.get("id"), UUID)
