"""FastAPI 认证依赖。"""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import CurrentAccount
from app.auth.repository import (
    ProfileReader,
    ProfileRepository,
    SqlAlchemyCurrentProfileReader,
    SqlAlchemyProfileRepository,
)
from app.auth.service import AccountService
from app.auth.supabase import SupabaseAuthError, SupabaseAuthGateway
from app.db import Database

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_gateway(request: Request) -> SupabaseAuthGateway:
    """读取应用启动时创建的 Supabase Auth 网关。"""

    gateway = getattr(request.app.state, "auth_gateway", None)
    if not isinstance(gateway, SupabaseAuthGateway):
        raise RuntimeError("Supabase Auth 网关尚未初始化")
    return gateway


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """为一个 HTTP 请求提供独立数据库事务。"""

    database: Database = request.app.state.database
    async with database.sessions() as session:
        yield session


def get_profile_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> ProfileRepository:
    """创建当前事务的账户仓库。"""

    return SqlAlchemyProfileRepository(session)


def get_current_profile_reader(request: Request) -> ProfileReader:
    """创建不会跨越当前账户查询的短会话读取器。"""

    database: Database = request.app.state.database
    return SqlAlchemyCurrentProfileReader(database)


def get_account_service(
    gateway: Annotated[SupabaseAuthGateway, Depends(get_auth_gateway)],
    profiles: Annotated[ProfileRepository, Depends(get_profile_repository)],
) -> AccountService:
    """创建当前请求的账户管理服务。"""

    return AccountService(gateway=gateway, profiles=profiles)


async def get_current_account(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    gateway: Annotated[SupabaseAuthGateway, Depends(get_auth_gateway)],
    profiles: Annotated[ProfileReader, Depends(get_current_profile_reader)],
) -> CurrentAccount:
    """在线验证访问令牌，并实时检查应用账户状态。"""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message": "需要登录"},
        )
    try:
        identity = await gateway.verify_user_token(credentials.credentials)
    except SupabaseAuthError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_session", "message": "登录已失效"},
        ) from error

    profile = await profiles.get_by_id(identity.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "profile_missing", "message": "账户未完成配置"},
        )
    if profile.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_disabled", "message": "账户已停用"},
        )
    return CurrentAccount(
        id=profile.id,
        email=identity.email,
        display_name=profile.display_name,
        role=profile.role,
        status=profile.status,
    )


async def require_admin(
    account: Annotated[CurrentAccount, Depends(get_current_account)],
) -> CurrentAccount:
    """只允许已启用的总管理员进入。"""

    if account.role != "admin" or account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "admin_required", "message": "需要管理员权限"},
        )
    return account


async def require_teacher(
    account: Annotated[CurrentAccount, Depends(get_current_account)],
) -> CurrentAccount:
    """只允许已启用的教师进入业务数据事务。"""

    if account.role != "teacher" or account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "teacher_required", "message": "需要教师权限"},
        )
    return account


async def get_teacher_database_session(
    request: Request,
    account: Annotated[CurrentAccount, Depends(require_teacher)],
) -> AsyncIterator[AsyncSession]:
    """提供带受限角色和可信 JWT claims 的教师事务。"""

    database: Database = request.app.state.database
    claims = json.dumps(
        {"sub": str(account.id), "role": "authenticated"},
        separators=(",", ":"),
    )
    async with database.sessions() as session, session.begin():
        await session.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": claims},
        )
        await session.execute(text("set local role paper_grading_teacher_api"))
        yield session
