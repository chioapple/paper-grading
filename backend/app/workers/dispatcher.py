"""Celery 投递器与 PostgreSQL 队列扫描。"""

import asyncio
from collections.abc import Callable
from uuid import UUID

from app.workers.repository import SqlAlchemyGradingJobRepository

GRADE_ITEM_TASK = "paper_grading.grade_item"


class CeleryGradingQueue:
    """只向 Redis 发送 UUID 和单调版本，不发送论文或模型快照。"""

    def __init__(self, sender: Callable[[UUID, int], None] | None = None) -> None:
        self._sender = sender or self._send_with_celery

    @staticmethod
    def _send_with_celery(item_id: UUID, dispatch_version: int) -> None:
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            GRADE_ITEM_TASK,
            args=[str(item_id), dispatch_version],
            task_id=f"grade-item:{item_id}:{dispatch_version}",
        )

    async def enqueue(self, item_id: UUID, dispatch_version: int) -> None:
        await asyncio.to_thread(self._sender, item_id, dispatch_version)


async def dispatch_ready_items(
    repository: SqlAlchemyGradingJobRepository,
    queue: CeleryGradingQueue,
    *,
    limit: int = 500,
) -> int:
    items = await repository.list_dispatchable_items(limit=limit)
    for item_id, dispatch_version in items:
        await queue.enqueue(item_id, dispatch_version)
    return len(items)
