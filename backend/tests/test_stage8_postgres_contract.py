"""阶段八独立 Supabase 测试项目的迁移契约。"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import TestMigrationSettings

STAGE_SEVEN_REVISION = "20260716_0009"
STAGE_EIGHT_REVISION = "20260716_0010"
EXPECTED_COLUMNS = {
    ("grading_jobs", "result_schema_version", "NO"),
    ("grading_jobs", "result_schema_hash", "NO"),
    ("grading_jobs", "rubric_hash", "NO"),
    ("grading_attempts", "request_version", "NO"),
}
PROTECTED_FUNCTIONS = {
    "paper_grading_protect_job_snapshot": (
        "NEW.result_schema_version",
        "NEW.result_schema_hash",
        "NEW.rubric_hash",
    ),
    "paper_grading_protect_attempt_history": ("NEW.request_version",),
}


def build_alembic_config() -> Config:
    return Config("backend/alembic.ini")


async def read_stage_eight_catalog(database_url: str) -> dict[str, object]:
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
                (row.table_name, row.column_name, row.is_nullable)
                for row in await connection.execute(
                    text(
                        """
                        select table_name, column_name, is_nullable
                        from information_schema.columns
                        where table_schema = 'public'
                          and (
                            (table_name = 'grading_jobs' and column_name in (
                              'result_schema_version', 'result_schema_hash', 'rubric_hash'
                            ))
                            or (table_name = 'grading_attempts'
                                and column_name = 'request_version')
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
                          'grading_attempts_request_check'
                        )
                        """
                    )
                )
            }
            functions = {
                row.proname: row
                for row in await connection.execute(
                    text(
                        """
                        select function_record.proname,
                               function_record.proconfig,
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
                          and function_record.proname in (
                            'paper_grading_protect_job_snapshot',
                            'paper_grading_protect_attempt_history'
                          )
                        """
                    )
                )
            }
            return {
                "revision": revision,
                "counts": counts,
                "columns": columns,
                "constraints": constraints,
                "functions": functions,
            }
    finally:
        await engine.dispose()


def assert_stage_eight_catalog(catalog: dict[str, object]) -> None:
    assert catalog["revision"] == STAGE_EIGHT_REVISION
    assert catalog["counts"] == {"grading_jobs": 0, "grading_attempts": 0}
    assert catalog["columns"] == EXPECTED_COLUMNS
    constraints = catalog["constraints"]
    assert isinstance(constraints, dict)
    assert "result_schema_version" in constraints["grading_jobs_snapshot_check"]
    assert "result_schema_hash" in constraints["grading_jobs_snapshot_check"]
    assert "rubric_hash" in constraints["grading_jobs_snapshot_check"]
    assert "request_version" in constraints["grading_attempts_request_check"]
    functions = catalog["functions"]
    assert isinstance(functions, dict)
    assert functions.keys() == PROTECTED_FUNCTIONS.keys()
    for function_name, protected_fields in PROTECTED_FUNCTIONS.items():
        function = functions[function_name]
        assert tuple(function.proconfig or ()) == ('search_path=""',)
        assert not function.public_can_execute
        assert not function.anon_can_execute
        assert not function.authenticated_can_execute
        assert not function.service_role_can_execute
        for protected_field in protected_fields:
            assert protected_field in function.definition


@pytest.mark.postgres
def test_stage_eight_snapshot_migration_replays_on_real_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只在用户显式运行时执行 0009→0010→0009→0010。"""

    settings = TestMigrationSettings()
    monkeypatch.setenv("MIGRATION_DATABASE_URL", settings.test_migration_database_url)
    config = build_alembic_config()
    before = asyncio.run(read_stage_eight_catalog(settings.test_migration_database_url))
    assert before["revision"] == STAGE_SEVEN_REVISION
    assert before["counts"] == {"grading_jobs": 0, "grading_attempts": 0}

    command.upgrade(config, STAGE_EIGHT_REVISION)
    try:
        assert_stage_eight_catalog(
            asyncio.run(read_stage_eight_catalog(settings.test_migration_database_url))
        )
        command.downgrade(config, STAGE_SEVEN_REVISION)
        rolled_back = asyncio.run(read_stage_eight_catalog(settings.test_migration_database_url))
        assert rolled_back["revision"] == STAGE_SEVEN_REVISION
        assert rolled_back["columns"] == set()
    finally:
        command.upgrade(config, STAGE_EIGHT_REVISION)

    assert_stage_eight_catalog(
        asyncio.run(read_stage_eight_catalog(settings.test_migration_database_url))
    )
