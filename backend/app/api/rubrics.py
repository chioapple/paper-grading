"""教师 Rubric 草稿、结构化、编辑与确认接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import require_teacher
from app.auth.models import CurrentAccount
from app.rubrics.dependencies import get_assignment_rubric_service
from app.rubrics.models import (
    AssignmentDetail,
    RubricDraftCreate,
    RubricStructuredUpdate,
    RubricStructureRequest,
    RubricView,
)
from app.rubrics.service import AssignmentRubricService

router = APIRouter(prefix="/assignments/{assignment_id}/rubrics", tags=["rubrics"])


@router.post("", response_model=RubricView, status_code=status.HTTP_201_CREATED)
async def create_rubric_draft(
    assignment_id: UUID,
    payload: RubricDraftCreate,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> RubricView:
    """为已有确认版创建下一版草稿，不覆盖旧版。"""

    return await service.create_rubric_draft(teacher.id, assignment_id, payload)


@router.post("/{rubric_id}/structure", response_model=RubricView)
async def structure_rubric(
    assignment_id: UUID,
    rubric_id: UUID,
    payload: RubricStructureRequest,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> RubricView:
    """使用所选供应商当前已测试默认模型生成结构化草稿。"""

    return await service.structure_rubric(
        teacher.id,
        assignment_id,
        rubric_id,
        payload,
    )


@router.put("/{rubric_id}", response_model=RubricView)
async def update_structured_rubric(
    assignment_id: UUID,
    rubric_id: UUID,
    payload: RubricStructuredUpdate,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> RubricView:
    """用教师核对后的完整对象替换结构化草稿。"""

    return await service.update_structured_rubric(
        teacher.id,
        assignment_id,
        rubric_id,
        payload,
    )


@router.post("/{rubric_id}/confirm", response_model=AssignmentDetail)
async def confirm_rubric(
    assignment_id: UUID,
    rubric_id: UUID,
    service: Annotated[AssignmentRubricService, Depends(get_assignment_rubric_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> AssignmentDetail:
    """原子冻结新版本、取代旧确认版并把作业置为 ready。"""

    return await service.confirm_rubric(teacher.id, assignment_id, rubric_id)
