"""阶段四真实 Supabase PostgreSQL 隔离验收。"""

import asyncio
from collections.abc import AsyncGenerator, Mapping
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_teacher_database_session
from app.auth.models import CurrentAccount
from app.config import Settings, TestMigrationSettings
from app.db import Database
from tests.auth_settings import TEST_AUTH_SETTINGS

pytestmark = pytest.mark.postgres
STAGE_FOUR_REVISION = "20260715_0006"
TEACHER_DATABASE_ROLE = "paper_grading_teacher_api"
BUSINESS_TABLES = {
    "profiles",
    "provider_configs",
    "assignments",
    "rubric_versions",
    "submissions",
    "grading_jobs",
    "grading_job_items",
    "grading_attempts",
    "teacher_reviews",
    "audit_logs",
    "exports",
}
ROLE_PRIVILEGES = {
    "profiles": {"SELECT"},
    "provider_configs": set(),
    "assignments": {"SELECT", "INSERT", "UPDATE"},
    "rubric_versions": {"SELECT", "INSERT", "UPDATE"},
    "submissions": {"SELECT", "INSERT"},
    "grading_jobs": {"SELECT", "INSERT"},
    "grading_job_items": {"SELECT", "INSERT"},
    "grading_attempts": {"SELECT"},
    "teacher_reviews": {"SELECT", "INSERT", "UPDATE"},
    "audit_logs": {"SELECT"},
    "exports": {"SELECT", "INSERT"},
}
EXPECTED_POLICIES = {
    ("profiles", "profiles_teacher_select", "SELECT"),
    *(
        (table_name, f"{table_name}_teacher_{command.lower()}", command)
        for table_name, commands in ROLE_PRIVILEGES.items()
        if table_name not in {"profiles", "provider_configs"}
        for command in commands
    ),
}


def test_stage_four_catalog_has_forced_rls_and_minimum_privileges() -> None:
    asyncio.run(check_stage_four_catalog())


async def check_stage_four_catalog() -> None:
    await check_teacher_catalog(STAGE_FOUR_REVISION)


async def check_teacher_catalog(
    expected_revision: str,
    *,
    expected_policies: set[tuple[str, str, str]] | None = None,
    expected_role_privileges: Mapping[str, set[str]] | None = None,
) -> None:
    settings = TestMigrationSettings()
    database = build_test_database(settings)
    try:
        async with database.engine.connect() as connection:
            revision = (
                await connection.execute(text("select version_num from alembic_version"))
            ).scalar_one()
            table_security = {
                row.relname: (row.relrowsecurity, row.relforcerowsecurity)
                for row in await connection.execute(
                    text(
                        "select class.relname, class.relrowsecurity, class.relforcerowsecurity "
                        "from pg_catalog.pg_class as class "
                        "join pg_catalog.pg_namespace as namespace "
                        "on namespace.oid = class.relnamespace "
                        "where namespace.nspname = 'public' and class.relkind = 'r'"
                    )
                )
                if row.relname in BUSINESS_TABLES
            }
            role = (
                await connection.execute(
                    text(
                        "select rolcanlogin, rolinherit, rolbypassrls "
                        "from pg_catalog.pg_roles where rolname = :role"
                    ),
                    {"role": TEACHER_DATABASE_ROLE},
                )
            ).one()
            postgres_can_set_role = (
                await connection.execute(
                    text("select pg_has_role('postgres', :role, 'MEMBER')"),
                    {"role": TEACHER_DATABASE_ROLE},
                )
            ).scalar_one()
            policies = {
                (row.tablename, row.policyname, row.cmd)
                for row in await connection.execute(
                    text(
                        "select tablename, policyname, cmd "
                        "from pg_catalog.pg_policies "
                        "where schemaname = 'public' "
                        "and :role = any(roles)"
                    ),
                    {"role": TEACHER_DATABASE_ROLE},
                )
            }
            helper = (
                await connection.execute(
                    text(
                        "select function_record.prosecdef, "
                        "cast(function_record.provolatile as text) as provolatile, "
                        "function_record.proconfig "
                        "from pg_catalog.pg_proc as function_record "
                        "join pg_catalog.pg_namespace as namespace "
                        "on namespace.oid = function_record.pronamespace "
                        "where namespace.nspname = 'paper_grading_private' "
                        "and function_record.proname = 'current_active_teacher_id'"
                    )
                )
            ).one()

            assert revision == expected_revision
            assert table_security == dict.fromkeys(BUSINESS_TABLES, (True, True))
            assert not role.rolcanlogin
            assert not role.rolinherit
            assert not role.rolbypassrls
            assert postgres_can_set_role
            assert policies == (
                EXPECTED_POLICIES if expected_policies is None else expected_policies
            )
            assert helper.prosecdef
            assert helper.provolatile == "s"
            assert tuple(helper.proconfig or ()) == ('search_path=""',)

            operations = {"SELECT", "INSERT", "UPDATE", "DELETE"}
            role_privileges = (
                ROLE_PRIVILEGES if expected_role_privileges is None else expected_role_privileges
            )
            for table_name, expected_privileges in role_privileges.items():
                for operation in operations:
                    has_teacher_privilege = (
                        await connection.execute(
                            text("select has_table_privilege(:role, :table, :operation)"),
                            {
                                "role": TEACHER_DATABASE_ROLE,
                                "table": f"public.{table_name}",
                                "operation": operation,
                            },
                        )
                    ).scalar_one()
                    assert has_teacher_privilege == (operation in expected_privileges)
                    for api_role in ("anon", "authenticated"):
                        has_data_api_privilege = (
                            await connection.execute(
                                text("select has_table_privilege(:role, :table, :operation)"),
                                {
                                    "role": api_role,
                                    "table": f"public.{table_name}",
                                    "operation": operation,
                                },
                            )
                        ).scalar_one()
                        assert not has_data_api_privilege
    finally:
        await database.dispose()


def test_stage_four_isolates_teachers_and_clears_pooled_identity() -> None:
    asyncio.run(check_teacher_isolation_and_pool_cleanup())


async def check_teacher_isolation_and_pool_cleanup() -> None:
    migration_settings = TestMigrationSettings()
    database = build_test_database(migration_settings)
    owner_id = migration_settings.test_teacher_auth_user_id
    other_owner_id = migration_settings.test_other_auth_user_id
    owner_assignment_id = uuid4()
    other_assignment_id = uuid4()
    open_dependencies: list[AsyncGenerator[AsyncSession, None]] = []
    seeded = False
    try:
        await seed_isolation_rows(
            database,
            owner_id=owner_id,
            other_owner_id=other_owner_id,
            owner_assignment_id=owner_assignment_id,
            other_assignment_id=other_assignment_id,
        )
        seeded = True
        request = cast(
            Request,
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=database))),
        )
        owner = build_teacher_account(owner_id, "Teacher A")
        other_owner = build_teacher_account(other_owner_id, "Teacher B")

        owner_dependency = cast(
            AsyncGenerator[AsyncSession, None],
            get_teacher_database_session(request, owner),
        )
        open_dependencies.append(owner_dependency)
        owner_session = await anext(owner_dependency)
        assert await owner_session.scalar(text("select current_user")) == TEACHER_DATABASE_ROLE
        assert (
            await owner_session.scalar(
                text("select paper_grading_private.current_active_teacher_id()")
            )
            == owner_id
        )
        visible_owner_ids = set(
            await owner_session.scalars(text("select owner_id from assignments"))
        )
        assert visible_owner_ids == {owner_id}
        cross_update = await owner_session.execute(
            text("update assignments set title = 'Blocked' where id = :id"),
            {"id": other_assignment_id},
        )
        assert cast(CursorResult[object], cross_update).rowcount == 0
        await assert_session_statement_rejected(
            owner_session,
            "insert into assignments (owner_id, title, instructions) "
            "values (:owner_id, 'Forged', 'Blocked')",
            {"owner_id": other_owner_id},
        )
        await assert_session_statement_rejected(
            owner_session,
            "delete from assignments where id = :id",
            {"id": other_assignment_id},
        )
        await assert_session_statement_rejected(
            owner_session,
            "update profiles set role = 'admin' where id = :id",
            {"id": owner_id},
        )
        await finish_dependency(owner_dependency)
        await assert_database_identity_is_clean(database)

        other_dependency = cast(
            AsyncGenerator[AsyncSession, None],
            get_teacher_database_session(request, other_owner),
        )
        open_dependencies.append(other_dependency)
        other_session = await anext(other_dependency)
        assert set(await other_session.scalars(text("select owner_id from assignments"))) == {
            other_owner_id
        }
        with pytest.raises(RuntimeError, match="force rollback"):
            await other_dependency.athrow(RuntimeError("force rollback"))
        await assert_database_identity_is_clean(database)

        await disable_profile(database, owner_id)
        disabled_dependency = cast(
            AsyncGenerator[AsyncSession, None],
            get_teacher_database_session(request, owner),
        )
        open_dependencies.append(disabled_dependency)
        disabled_session = await anext(disabled_dependency)
        assert list(await disabled_session.scalars(text("select id from assignments"))) == []
        await assert_session_statement_rejected(
            disabled_session,
            "insert into assignments (owner_id, title, instructions) "
            "values (:owner_id, 'Disabled', 'Blocked')",
            {"owner_id": owner_id},
        )
        await finish_dependency(disabled_dependency)
    finally:
        try:
            for dependency in reversed(open_dependencies):
                await dependency.aclose()
            if seeded:
                await cleanup_isolation_rows(
                    database,
                    owner_id=owner_id,
                    other_owner_id=other_owner_id,
                )
        finally:
            await database.dispose()


def build_test_database(settings: TestMigrationSettings) -> Database:
    return Database.from_settings(
        Settings(
            APP_ENV="test",
            DATABASE_URL=settings.test_database_url,
            DATABASE_POOL_SIZE=1,
            DATABASE_POOL_TIMEOUT_SECONDS=5,
            **TEST_AUTH_SETTINGS,
        )
    )


def build_teacher_account(user_id: UUID, display_name: str) -> CurrentAccount:
    return CurrentAccount(
        id=user_id,
        email=f"{user_id}@example.com",
        display_name=display_name,
        role="teacher",
        status="active",
    )


async def seed_isolation_rows(
    database: Database,
    *,
    owner_id: UUID,
    other_owner_id: UUID,
    owner_assignment_id: UUID,
    other_assignment_id: UUID,
) -> None:
    async with database.engine.begin() as connection:
        expected_auth_ids = {owner_id, other_owner_id}
        auth_ids = set(
            await connection.scalars(
                text("select id from auth.users where id in (:owner_id, :other_owner_id)"),
                {"owner_id": owner_id, "other_owner_id": other_owner_id},
            )
        )
        missing_auth_ids = expected_auth_ids - auth_ids
        if missing_auth_ids:
            missing_ids = ", ".join(sorted(str(user_id) for user_id in missing_auth_ids))
            pytest.fail(
                "阶段四隔离测试缺少 Auth 测试用户。请在独立 Supabase 测试项目创建"
                "两个未受邀用户，并把真实 UUID 写入 .env.stage2-test 的 "
                "TEST_TEACHER_AUTH_USER_ID 和 TEST_OTHER_AUTH_USER_ID。测试不会自动选择、"
                f"创建或删除 Auth 用户。当前缺少：{missing_ids}",
                pytrace=False,
            )
        profile_ids = set(
            await connection.scalars(
                text("select id from profiles where id in (:owner_id, :other_owner_id)"),
                {"owner_id": owner_id, "other_owner_id": other_owner_id},
            )
        )
        if profile_ids:
            occupied_ids = ", ".join(sorted(str(user_id) for user_id in profile_ids))
            pytest.fail(
                "阶段四隔离测试用户不得已有 profile。请改用两个未受邀 Auth 用户并更新"
                " .env.stage2-test 的 TEST_TEACHER_AUTH_USER_ID 和 "
                f"TEST_OTHER_AUTH_USER_ID。当前已占用：{occupied_ids}",
                pytrace=False,
            )
        await connection.execute(
            text(
                "insert into profiles (id, role, status, display_name) values "
                "(:owner_id, 'teacher', 'active', 'Stage Four Teacher A'), "
                "(:other_owner_id, 'teacher', 'active', 'Stage Four Teacher B')"
            ),
            {"owner_id": owner_id, "other_owner_id": other_owner_id},
        )
        await connection.execute(
            text(
                "insert into assignments (id, owner_id, title, instructions) values "
                "(:owner_assignment_id, :owner_id, 'Teacher A', 'A'), "
                "(:other_assignment_id, :other_owner_id, 'Teacher B', 'B')"
            ),
            {
                "owner_assignment_id": owner_assignment_id,
                "owner_id": owner_id,
                "other_assignment_id": other_assignment_id,
                "other_owner_id": other_owner_id,
            },
        )


async def disable_profile(database: Database, user_id: UUID) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(
            text("update profiles set status = 'disabled' where id = :id"),
            {"id": user_id},
        )


async def cleanup_isolation_rows(
    database: Database,
    *,
    owner_id: UUID,
    other_owner_id: UUID,
) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(
            text("delete from assignments where owner_id in (:owner_id, :other_owner_id)"),
            {"owner_id": owner_id, "other_owner_id": other_owner_id},
        )
        await connection.execute(
            text("delete from profiles where id in (:owner_id, :other_owner_id)"),
            {"owner_id": owner_id, "other_owner_id": other_owner_id},
        )


async def assert_session_statement_rejected(
    session: AsyncSession,
    statement: str,
    parameters: Mapping[str, object],
) -> None:
    savepoint = await session.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await session.execute(text(statement), parameters)
    finally:
        if savepoint.is_active:
            await savepoint.rollback()


async def finish_dependency(dependency: AsyncGenerator[AsyncSession, None]) -> None:
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)


async def assert_database_identity_is_clean(database: Database) -> None:
    async with database.sessions() as session:
        assert await session.scalar(text("select current_user")) != TEACHER_DATABASE_ROLE
        claims = await session.scalar(text("select current_setting('request.jwt.claims', true)"))
        assert claims in {None, ""}
        assert await session.scalar(text("select auth.uid()")) is None
