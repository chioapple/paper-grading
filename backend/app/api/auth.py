"""当前会话接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_account_service, get_current_account
from app.auth.models import CurrentAccount
from app.auth.service import AccountService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentAccount)
async def read_current_account(
    account: Annotated[CurrentAccount, Depends(get_current_account)],
) -> CurrentAccount:
    """返回经服务端验证的应用角色与状态。"""

    return account


@router.post("/complete-invite", response_model=CurrentAccount)
async def complete_invite(
    account: Annotated[CurrentAccount, Depends(get_current_account)],
    service: Annotated[AccountService, Depends(get_account_service)],
) -> CurrentAccount:
    """首次设密后幂等激活受邀教师。"""

    profile = await service.complete_invite(account.id)
    return CurrentAccount(
        id=profile.id,
        email=account.email,
        display_name=profile.display_name,
        role=profile.role,
        status=profile.status,
    )
