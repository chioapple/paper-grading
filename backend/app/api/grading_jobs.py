"""阶段十教师批次、控制和 PostgreSQL 进度流接口。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import require_teacher
from app.auth.models import CurrentAccount
from app.workers.dependencies import get_grading_job_service
from app.workers.models import GradingJobCreate, GradingJobView
from app.workers.service import GradingJobService

router = APIRouter(tags=["grading-jobs"])


class GradingJobRequest(BaseModel):
    """幂等键走请求头，正文只包含有序且不重复的论文 ID。"""

    model_config = ConfigDict(extra="forbid")

    submission_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)


@router.post(
    "/assignments/{assignment_id}/grading-jobs",
    response_model=GradingJobView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_grading_job(
    assignment_id: UUID,
    payload: GradingJobRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.create_job(
        teacher.id,
        assignment_id,
        GradingJobCreate(
            submission_ids=payload.submission_ids,
            idempotency_key=idempotency_key,
        ),
    )


@router.get("/grading-jobs/{job_id}", response_model=GradingJobView)
async def get_grading_job(
    job_id: UUID,
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.get_job(teacher.id, job_id)


@router.post("/grading-jobs/{job_id}/pause", response_model=GradingJobView)
async def pause_grading_job(
    job_id: UUID,
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.pause_job(teacher.id, job_id)


@router.post("/grading-jobs/{job_id}/resume", response_model=GradingJobView)
async def resume_grading_job(
    job_id: UUID,
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.resume_job(teacher.id, job_id)


@router.post("/grading-jobs/{job_id}/cancel", response_model=GradingJobView)
async def cancel_grading_job(
    job_id: UUID,
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.cancel_job(teacher.id, job_id)


@router.post("/grading-jobs/{job_id}/items/{item_id}/retry", response_model=GradingJobView)
async def retry_grading_item(
    job_id: UUID,
    item_id: UUID,
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> GradingJobView:
    return await service.retry_item(teacher.id, job_id, item_id)


@router.get("/grading-jobs/{job_id}/events")
async def stream_grading_job_events(
    job_id: UUID,
    request: Request,
    service: Annotated[GradingJobService, Depends(get_grading_job_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> StreamingResponse:
    """断线重连后重新读取 PostgreSQL；Redis/Celery 不参与进度计算。"""

    async def events() -> AsyncIterator[bytes]:
        last_version: int | None = None
        while True:
            job = await service.get_job(teacher.id, job_id)
            settled = job.queued == 0 and job.running == 0
            if job.state_version != last_version:
                payload = json.dumps(
                    {"job": job.model_dump(mode="json"), "settled": settled},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield (f"id: {job.state_version}\nevent: progress\ndata: {payload}\n\n").encode()
                last_version = job.state_version
            if settled or await request.is_disconnected():
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
