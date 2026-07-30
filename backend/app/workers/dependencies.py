"""阶段十批次服务的 FastAPI 依赖装配。"""

from typing import cast

from fastapi import Request

from app.db import Database
from app.workers.dispatcher import CeleryGradingQueue
from app.workers.repository import SqlAlchemyGradingJobRepository
from app.workers.service import GradingJobService, GradingQueue


def get_grading_job_service(request: Request) -> GradingJobService:
    """每次请求创建短事务仓库，并复用应用级 Celery 投递器。"""

    database: Database = request.app.state.database
    queue = getattr(request.app.state, "grading_queue", None)
    if queue is None:
        queue = CeleryGradingQueue()
        request.app.state.grading_queue = queue
    return GradingJobService(
        repository=SqlAlchemyGradingJobRepository(database),
        queue=cast(GradingQueue, queue),
    )
