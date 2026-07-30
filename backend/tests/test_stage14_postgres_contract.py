"""阶段 14 独立 Supabase 全链迁移回放门禁。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import TestMigrationSettings
from tests.security.test_stage_four_postgres import (
    EXPECTED_POLICIES,
    ROLE_PRIVILEGES,
    check_teacher_catalog,
    check_teacher_isolation_and_pool_cleanup,
)
from tests.test_stage10_postgres_contract import (
    assert_stage_ten_catalog,
    assert_teacher_batch_permission_contract,
    read_stage_ten_catalog,
)
from tests.test_stage12_postgres_contract import (
    assert_stage_twelve_catalog,
    read_stage_twelve_catalog,
)

STAGE_FOURTEEN_REVISION = "20260728_0019"
STAGE_THIRTEEN_REVISION = "20260726_0018"
STAGE_TWELVE_REVISION = "20260722_0017"
STAGE_FOURTEEN_TEACHER_POLICIES = EXPECTED_POLICIES - {
    ("exports", "exports_teacher_insert", "INSERT")
} | {("export_items", "export_items_teacher_select", "SELECT")}
STAGE_FOURTEEN_TEACHER_PRIVILEGES = {
    **ROLE_PRIVILEGES,
    "teacher_reviews": {"SELECT"},
    "exports": {"SELECT"},
}

pytestmark = pytest.mark.postgres


async def run_alembic(
    connection: AsyncConnection,
    config: Config,
    operation: Callable[[Config, str], None],
    revision: str,
) -> None:
    if connection.in_transaction():
        raise RuntimeError("Alembic 迁移前必须结束调用方事务")

    def invoke(sync_connection: Connection) -> None:
        config.attributes["connection"] = sync_connection
        try:
            operation(config, revision)
        finally:
            config.attributes.pop("connection", None)

    await connection.run_sync(invoke)


async def current_revision(connection: AsyncConnection) -> str | None:
    exists = await connection.scalar(text("select to_regclass('public.alembic_version')"))
    if exists is None:
        await connection.commit()
        return None
    revision = await connection.scalar(text("select version_num from alembic_version"))
    await connection.commit()
    return cast(str | None, revision)


async def read_grading_worker_login_contract(
    settings: TestMigrationSettings,
) -> tuple[bool, bool, bool, bool, bool, bool]:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            role = (
                await connection.execute(
                    text(
                        """
                        select rolcanlogin,
                               rolinherit,
                               rolbypassrls,
                               has_schema_privilege(
                                   'paper_grading_worker',
                                   'paper_grading_private',
                                   'usage'
                               ),
                               has_function_privilege(
                                   'paper_grading_worker',
                                   'paper_grading_private.reserve_storage_growth('
                                   'text,text,bytea,bigint)',
                                   'execute'
                               ),
                               has_function_privilege(
                                   'paper_grading_worker',
                                   'paper_grading_private.finalize_storage_growth(uuid,text)',
                                   'execute'
                               )
                        from pg_catalog.pg_roles
                        where rolname = 'paper_grading_worker'
                        """
                    )
                )
            ).one()
            return cast(tuple[bool, bool, bool, bool, bool, bool], tuple(role))
    finally:
        await engine.dispose()


async def read_current_grading_worker_catalog(settings: TestMigrationSettings) -> dict[str, object]:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await read_stage_ten_catalog(connection)
    finally:
        await engine.dispose()


async def replay_from_empty(settings: TestMigrationSettings) -> None:
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    config = Config("backend/alembic.ini")
    try:
        async with engine.connect() as connection:
            auth_count = await connection.scalar(
                text(
                    "select count(*) from auth.users where id in (:teacher_id, :other_teacher_id)"
                ),
                {
                    "teacher_id": settings.test_teacher_auth_user_id,
                    "other_teacher_id": settings.test_other_auth_user_id,
                },
            )
            await connection.commit()
            assert auth_count == 2, "独立测试项目必须预先存在两个 Auth 测试用户"

            initial_revision = await current_revision(connection)
            assert initial_revision in {
                None,
                STAGE_THIRTEEN_REVISION,
                STAGE_FOURTEEN_REVISION,
            }
            try:
                if initial_revision in {None, STAGE_THIRTEEN_REVISION}:
                    await run_alembic(
                        connection,
                        config,
                        command.upgrade,
                        STAGE_FOURTEEN_REVISION,
                    )
                    assert await current_revision(connection) == STAGE_FOURTEEN_REVISION

                await run_alembic(
                    connection,
                    config,
                    command.downgrade,
                    STAGE_TWELVE_REVISION,
                )
                assert await current_revision(connection) == STAGE_TWELVE_REVISION

                await run_alembic(
                    connection,
                    config,
                    command.upgrade,
                    STAGE_FOURTEEN_REVISION,
                )
                assert await current_revision(connection) == STAGE_FOURTEEN_REVISION
            finally:
                if await current_revision(connection) != STAGE_FOURTEEN_REVISION:
                    await run_alembic(
                        connection,
                        config,
                        command.upgrade,
                        STAGE_FOURTEEN_REVISION,
                    )
    finally:
        await engine.dispose()


def test_fresh_database_upgrades_to_0019_then_rolls_back_and_reupgrades() -> None:
    asyncio.run(replay_from_empty(TestMigrationSettings()))


def test_current_head_teacher_rls_deactivation_and_admin_boundary() -> None:
    asyncio.run(
        check_teacher_catalog(
            STAGE_FOURTEEN_REVISION,
            expected_policies=STAGE_FOURTEEN_TEACHER_POLICIES,
            expected_role_privileges=STAGE_FOURTEEN_TEACHER_PRIVILEGES,
        )
    )
    asyncio.run(check_teacher_isolation_and_pool_cleanup())


def test_current_head_teacher_batch_permissions_and_idempotency() -> None:
    asyncio.run(
        assert_teacher_batch_permission_contract(
            expected_revision=STAGE_FOURTEEN_REVISION,
        )
    )


def test_current_head_export_worker_has_minimum_role() -> None:
    catalog = asyncio.run(read_stage_twelve_catalog(TestMigrationSettings()))
    assert_stage_twelve_catalog(catalog, STAGE_FOURTEEN_REVISION)


def test_current_head_grading_worker_is_a_dedicated_minimum_login_role() -> None:
    settings = TestMigrationSettings()
    catalog = asyncio.run(read_current_grading_worker_catalog(settings))
    assert_stage_ten_catalog(
        catalog,
        STAGE_FOURTEEN_REVISION,
        expected_worker_login=True,
        require_empty_grading_tables=False,
    )
    role = asyncio.run(read_grading_worker_login_contract(settings))
    assert role == (True, False, False, True, True, True)
