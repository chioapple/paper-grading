"""阶段十一教师复核服务的 FastAPI 装配。"""

from typing import cast

from fastapi import Request

from app.db import Database
from app.reviews.repository import SqlAlchemyReviewRepository
from app.reviews.service import ReviewObjectStorage, ReviewService
from app.workers.dependencies import get_grading_job_service


def get_review_service(request: Request) -> ReviewService:
    """复用应用级私有存储和阶段十固定快照重评服务。"""

    database: Database = request.app.state.database
    return ReviewService(
        repository=SqlAlchemyReviewRepository(database),
        storage=cast(ReviewObjectStorage, request.app.state.object_storage),
        regrader=get_grading_job_service(request),
    )
