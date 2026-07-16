"""阶段九独立 Supabase 测试项目的迁移契约。"""

import asyncio
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import TestMigrationSettings

STAGE_EIGHT_REVISION = "20260716_0010"
STAGE_NINE_REVISION = "20260716_0011"
EXPECTED_COLUMNS = {
    ("grading_jobs", "provider_config_version", "integer", "NO"),
    ("grading_jobs", "result_schema", "jsonb", "NO"),
    ("grading_attempts", "raw_response_sha256", "bytea", "YES"),
}


def build_alembic_config() -> Config:
    return Config("backend/alembic.ini")


async def read_stage_nine_catalog(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            revision = (
                await connection.execute(text("select version_num from alembic_version"))
            ).scalar_one()
            counts = {
                row.table_name: row.row_count
                for row in await connection.execute(
                    text(
                        """
                        select 'grading_jobs' as table_name, count(*) as row_count
                        from public.grading_jobs
                        union all
                        select 'grading_attempts' as table_name, count(*) as row_count
                        from public.grading_attempts
                        """
                    )
                )
            }
            columns = {
                (row.table_name, row.column_name, row.data_type, row.is_nullable)
                for row in await connection.execute(
                    text(
                        """
                        select table_name, column_name, data_type, is_nullable
                        from information_schema.columns
                        where table_schema = 'public'
                          and (
                            (table_name = 'grading_jobs' and column_name in (
                              'provider_config_version', 'result_schema'
                            ))
                            or (table_name = 'grading_attempts'
                                and column_name = 'raw_response_sha256')
                          )
                        """
                    )
                )
            }
            constraints = {
                row.conname: row.definition
                for row in await connection.execute(
                    text(
                        """
                        select constraint_record.conname,
                               pg_get_constraintdef(constraint_record.oid) as definition
                        from pg_catalog.pg_constraint as constraint_record
                        where constraint_record.conname in (
                          'grading_jobs_snapshot_check',
                          'grading_attempts_raw_response_check'
                        )
                        """
                    )
                )
            }
            function = (
                await connection.execute(
                    text(
                        """
                        select function_record.proconfig,
                               pg_get_functiondef(function_record.oid) as definition,
                               exists (
                                 select 1
                                 from pg_catalog.aclexplode(
                                   coalesce(
                                     function_record.proacl,
                                     pg_catalog.acldefault('f', function_record.proowner)
                                   )
                                 ) as privilege
                                 where privilege.grantee = 0
                                   and privilege.privilege_type = 'EXECUTE'
                               ) as public_can_execute,
                               has_function_privilege(
                                 'anon', function_record.oid, 'execute'
                               ) as anon_can_execute,
                               has_function_privilege(
                                 'authenticated', function_record.oid, 'execute'
                               ) as authenticated_can_execute,
                               has_function_privilege(
                                 'service_role', function_record.oid, 'execute'
                               ) as service_role_can_execute
                        from pg_catalog.pg_proc as function_record
                        join pg_catalog.pg_namespace as namespace
                          on namespace.oid = function_record.pronamespace
                        where namespace.nspname = 'public'
                          and function_record.proname = 'paper_grading_protect_job_snapshot'
                        """
                    )
                )
            ).one()
            return {
                "revision": revision,
                "counts": counts,
                "columns": columns,
                "constraints": constraints,
                "function": function,
            }
    finally:
        await engine.dispose()


def assert_stage_nine_catalog(catalog: dict[str, object]) -> None:
    assert catalog["revision"] == STAGE_NINE_REVISION
    assert catalog["counts"] == {"grading_jobs": 0, "grading_attempts": 0}
    assert catalog["columns"] == EXPECTED_COLUMNS
    constraints = catalog["constraints"]
    assert isinstance(constraints, dict)
    assert "provider_config_version > 0" in constraints["grading_jobs_snapshot_check"]
    assert "jsonb_typeof(result_schema)" in constraints["grading_jobs_snapshot_check"]
    assert (
        "octet_length(raw_response_sha256) = 32"
        in constraints["grading_attempts_raw_response_check"]
    )
    function = cast(Any, catalog["function"])
    assert tuple(function.proconfig or ()) == ('search_path=""',)
    assert "NEW.provider_config_version" in function.definition
    assert "NEW.result_schema" in function.definition
    assert not function.public_can_execute
    assert not function.anon_can_execute
    assert not function.authenticated_can_execute
    assert not function.service_role_can_execute


@pytest.mark.postgres
def test_stage_nine_provider_call_migration_replays_on_real_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只在用户显式运行时执行 0010→0011→0010→0011。"""

    settings = TestMigrationSettings()
    monkeypatch.setenv("MIGRATION_DATABASE_URL", settings.test_migration_database_url)
    config = build_alembic_config()
    before = asyncio.run(read_stage_nine_catalog(settings.test_migration_database_url))
    assert before["revision"] == STAGE_EIGHT_REVISION
    assert before["counts"] == {"grading_jobs": 0, "grading_attempts": 0}

    command.upgrade(config, STAGE_NINE_REVISION)
    try:
        assert_stage_nine_catalog(
            asyncio.run(read_stage_nine_catalog(settings.test_migration_database_url))
        )
        command.downgrade(config, STAGE_EIGHT_REVISION)
        rolled_back = asyncio.run(read_stage_nine_catalog(settings.test_migration_database_url))
        assert rolled_back["revision"] == STAGE_EIGHT_REVISION
        assert rolled_back["counts"] == {"grading_jobs": 0, "grading_attempts": 0}
        command.upgrade(config, STAGE_NINE_REVISION)
        assert_stage_nine_catalog(
            asyncio.run(read_stage_nine_catalog(settings.test_migration_database_url))
        )
    finally:
        current = asyncio.run(read_stage_nine_catalog(settings.test_migration_database_url))
        if current["revision"] != STAGE_NINE_REVISION:
            command.upgrade(config, STAGE_NINE_REVISION)
