"""阶段十一教师复核工作台接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_teacher
from app.auth.models import CurrentAccount
from app.reviews.dependencies import get_review_service
from app.reviews.models import (
    ReviewBatchConfirmationInput,
    ReviewConfirmationResult,
    ReviewDetail,
    ReviewDraftInput,
    ReviewDraftView,
    ReviewJobSummary,
)
from app.reviews.service import ReviewService
from app.workers.models import GradingJobView

router = APIRouter(tags=["reviews"])


@router.get("/grading-jobs", response_model=tuple[ReviewJobSummary, ...])
async def list_review_jobs(
    service: Annotated[ReviewService, Depends(get_review_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> tuple[ReviewJobSummary, ...]:
    return await service.list_jobs(teacher.id)


@router.get(
    "/grading-jobs/{job_id}/items/{item_id}/review",
    response_model=ReviewDetail,
)
async def get_review_detail(
    job_id: UUID,
    item_id: UUID,
    service: Annotated[ReviewService, Depends(get_review_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ReviewDetail:
    return await service.get_detail(teacher.id, item_id, job_id=job_id)


@router.put(
    "/grading-jobs/{job_id}/items/{item_id}/review",
    response_model=ReviewDraftView,
)
async def save_review_draft(
    job_id: UUID,
    item_id: UUID,
    payload: ReviewDraftInput,
    service: Annotated[ReviewService, Depends(get_review_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ReviewDraftView:
    return await service.save_draft(teacher.id, item_id, payload, job_id=job_id)


@router.post(
    "/grading-jobs/{job_id}/items/{item_id}/review/confirm",
    response_model=ReviewConfirmationResult,
)
async def confirm_review(
    job_id: UUID,
    item_id: UUID,
    payload: ReviewDraftInput,
    service: Annotated[ReviewService, Depends(get_review_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ReviewConfirmationResult:
    return await service.confirm(teacher.id, job_id, item_id, payload)


@router.post(
    "/grading-jobs/{job_id}/reviews/batch-confirm",
    response_model=ReviewConfirmationResult,
)
async def confirm_review_batch(
    job_id: UUID,
    payload: ReviewBatchConfirmationInput,
    service: Annotated[ReviewService, Depends(get_review_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> ReviewConfirmationResult:
    return await service.confirm_batch(teacher.id, job_id, payload.reviews)


@router.post(
    "/grading-jobs/{job_id}/items/{item_id}/review/regrade",
    response_model=GradingJobView,
)
async def regrade_review_item(
    job_id: UUID,
    item_id: UUID,
    service: Annotated[ReviewService, Depends(get_review_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.regrade(teacher.id, job_id, item_id)
