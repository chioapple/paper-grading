"""教师作业列表、创建、详情与状态接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import require_teacher
from app.auth.models import CurrentAccount
from app.rubrics.dependencies import get_assignment_rubric_service
from app.rubrics.models import (
    AssignmentCreate,
    AssignmentDetail,
    AssignmentStatusUpdate,
    AssignmentSummary,
    AssignmentUpdate,
)
from app.rubrics.service import AssignmentRubricService

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.get("", response_model=list[AssignmentSummary])
async def list_assignments(
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> list[AssignmentSummary]:
    """按创建时间倒序列出当前教师的作业。"""

    return await service.list_assignments(teacher.id)


@router.post("", response_model=AssignmentDetail, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    payload: AssignmentCreate,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> AssignmentDetail:
    """在一个事务中创建作业及 Rubric v1 草稿。"""

    return await service.create_assignment(teacher.id, payload)


@router.get("/{assignment_id}", response_model=AssignmentDetail)
async def get_assignment(
    assignment_id: UUID,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> AssignmentDetail:
    """返回当前教师名下的作业和全部 Rubric 版本。"""

    return await service.get_assignment(teacher.id, assignment_id)


@router.put("/{assignment_id}", response_model=AssignmentDetail)
async def update_assignment(
    assignment_id: UUID,
    payload: AssignmentUpdate,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> AssignmentDetail:
    """只允许替换草稿作业的标题和要求。"""

    return await service.update_assignment(teacher.id, assignment_id, payload)


@router.put("/{assignment_id}/status", response_model=AssignmentDetail)
async def update_assignment_status(
    assignment_id: UUID,
    payload: AssignmentStatusUpdate,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> AssignmentDetail:
    """归档或恢复作业；恢复时按已确认 Rubric 原子恢复为 ready 或 draft。"""

    return await service.update_assignment_status(teacher.id, assignment_id, payload)
