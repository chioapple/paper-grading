"""教师数据库事务身份测试。"""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_teacher_database_session, require_teacher
from app.auth.models import CurrentAccount
from app.auth.repository import SqlAlchemyCurrentProfileReader
from app.db import Database
from app.domain.models import Profile


class RecordingSession:
    """记录事务边界和身份配置的最小测试会话。"""

    def __init__(self) -> None:
        self.in_transaction = False
        self.statements: list[tuple[str, object | None]] = []

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        self.in_transaction = True
        try:
            yield
        finally:
            self.in_transaction = False

    async def execute(self, statement: object, parameters: object | None = None) -> None:
        self.statements.append((str(statement), parameters))


def test_current_profile_reader_closes_its_session_before_returning() -> None:
    user_id = UUID("00000000-0000-0000-0000-000000000103")
    events: list[str] = []

    class ProfileSession:
        async def get(self, model: object, identity: UUID) -> Profile:
            assert model is Profile
            assert identity == user_id
            events.append("read")
            return Profile(
                id=user_id,
                display_name="Teacher",
                role="teacher",
                status="active",
            )

    @asynccontextmanager
    async def open_session() -> AsyncIterator[AsyncSession]:
        events.append("open")
        try:
            yield cast(AsyncSession, ProfileSession())
        finally:
            events.append("close")

    database = cast(Database, SimpleNamespace(sessions=open_session))
    reader = SqlAlchemyCurrentProfileReader(database)

    profile = asyncio.run(reader.get_by_id(user_id))

    assert profile is not None
    assert profile.id == user_id
    assert events == ["open", "read", "close"]


def test_teacher_database_session_sets_transaction_local_identity() -> None:
    teacher_id = UUID("00000000-0000-0000-0000-000000000101")
    account = CurrentAccount(
        id=teacher_id,
        email="teacher@example.com",
        display_name="Teacher",
        role="teacher",
        status="active",
    )
    session = RecordingSession()

    @asynccontextmanager
    async def open_session() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    database = cast(Database, SimpleNamespace(sessions=open_session))
    request = cast(
        Request,
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=database))),
    )

    async def run_scenario() -> None:
        dependency = cast(
            AsyncGenerator[AsyncSession, None],
            get_teacher_database_session(request, account),
        )
        yielded_session = await anext(dependency)
        assert yielded_session is cast(AsyncSession, session)
        assert session.in_transaction
        await dependency.aclose()

    asyncio.run(run_scenario())

    assert not session.in_transaction
    assert session.statements == [
        (
            "select set_config('request.jwt.claims', :claims, true)",
            {
                "claims": json.dumps(
                    {"sub": str(teacher_id), "role": "authenticated"},
                    separators=(",", ":"),
                )
            },
        ),
        ("set local role paper_grading_teacher_api", None),
    ]


@pytest.mark.parametrize(
    ("role", "account_status"),
    [("admin", "active"), ("teacher", "invited")],
)
def test_only_active_teachers_can_open_business_transactions(
    role: str,
    account_status: str,
) -> None:
    account = CurrentAccount.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000102",
            "email": "account@example.com",
            "display_name": "Account",
            "role": role,
            "status": account_status,
        }
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(require_teacher(account))

    assert error.value.status_code == 403
    detail = cast(dict[str, object], cast(object, error.value.detail))
    assert detail.get("code") == "teacher_required"
