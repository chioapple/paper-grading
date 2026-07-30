"""只向 Redis 发送 export UUID 的导出队列边界。"""

from collections.abc import Callable
from uuid import UUID

EXPORT_TASK = "paper_grading.generate_export"
EXPORT_QUEUE = "paper_grading.exports"


class CeleryExportQueue:
    def __init__(self, sender: Callable[[UUID], None] | None = None) -> None:
        self._sender = sender or self._send_with_celery

    @staticmethod
    def _send_with_celery(export_id: UUID) -> None:
        from app.export.celery_app import celery_app

        celery_app.send_task(
            EXPORT_TASK,
            args=[str(export_id)],
            queue=EXPORT_QUEUE,
        )

    async def enqueue(self, export_id: UUID) -> None:
        self._sender(export_id)
