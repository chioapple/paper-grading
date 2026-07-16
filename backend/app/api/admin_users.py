"""管理员教师账户接口。"""

import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator

from app.auth.dependencies import get_account_service, require_admin
from app.auth.models import CurrentAccount, TeacherAccount
from app.auth.service import AccountService

router = APIRouter(prefix="/admin/users", tags=["admin-users"])
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


class InviteTeacherRequest(BaseModel):
    """管理员发送教师邀请所需的最小字段。"""

    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("邮箱格式无效")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("姓名不能为空")
        return normalized


@router.get("", response_model=list[TeacherAccount])
async def list_teacher_accounts(
    service: Annotated[AccountService, Depends(get_account_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> list[TeacherAccount]:
    """列出受控教师账户。"""

    return await service.list_teachers()


@router.post(
    "/invitations",
    response_model=TeacherAccount,
    status_code=status.HTTP_201_CREATED,
)
async def invite_teacher(
    payload: InviteTeacherRequest,
    service: Annotated[AccountService, Depends(get_account_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> TeacherAccount:
    """邀请一个教师账户，不提供公开注册入口。"""

    return await service.invite_teacher(
        email=payload.email,
        display_name=payload.display_name,
    )


@router.post("/{teacher_id}/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_teacher(
    teacher_id: UUID,
    service: Annotated[AccountService, Depends(get_account_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> Response:
    """停用一个正常教师账户。"""

    await service.disable_teacher(teacher_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{teacher_id}/enable", status_code=status.HTTP_204_NO_CONTENT)
async def enable_teacher(
    teacher_id: UUID,
    service: Annotated[AccountService, Depends(get_account_service)],
    _admin: Annotated[CurrentAccount, Depends(require_admin)],
) -> Response:
    """启用一个已停用教师账户。"""

    await service.enable_teacher(teacher_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
