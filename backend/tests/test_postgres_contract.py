"""真实 PostgreSQL 上的阶段 2 迁移与约束验收。"""

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import TestMigrationSettings
from app.domain.models import Base

pytestmark = pytest.mark.postgres
BACKEND_ROOT = Path(__file__).parents[1]
STAGE_TWO_REVISION = "20260714_0003"
STAGE_TWO_PUBLISHED_REVISION = "20260713_0002"
STAGE_TWO_BASE_REVISION = "20260713_0001"
EXPECTED_TABLES = {table.name for table in Base.metadata.tables.values() if table.schema is None}
LATER_STAGE_CONSTRAINTS = {
    "provider_configs_test_version_check",
    "provider_configs_text_check",
    "provider_configs_default_model_check",
    "assignments_instructions_check",
    "rubric_versions_provider_config_id_fkey",
    "rubric_versions_generation_check",
    "rubric_versions_content_check",
}
EXPECTED_CONSTRAINTS = {
    str(constraint.name)
    for table in Base.metadata.tables.values()
    if table.schema is None
    for constraint in table.constraints
    if constraint.name is not None
} - LATER_STAGE_CONSTRAINTS
LATER_STAGE_INDEXES = {
    "rubric_versions_provider_config_id_idx",
    "rubric_versions_one_draft_idx",
    "rubric_versions_one_confirmed_idx",
}
EXPECTED_INDEXES = {
    str(index.name)
    for table in Base.metadata.tables.values()
    if table.schema is None
    for index in table.indexes
    if index.name is not None
} - LATER_STAGE_INDEXES
EXPECTED_TRIGGERS = {
    "profiles_set_updated_at",
    "provider_configs_set_updated_at",
    "assignments_set_updated_at",
    "audit_logs_reject_mutation",
    "grading_attempts_require_running_insert",
    "grading_attempts_protect_history",
    "teacher_reviews_protect_history",
    "grading_attempts_validate_rubric_score",
    "teacher_reviews_validate_attempt_score",
    "rubric_versions_protect_history",
    "grading_jobs_protect_snapshot",
}
EXPECTED_STAGE_TWO_FUNCTIONS = {
    "paper_grading_set_updated_at",
    "paper_grading_protect_rubric_history",
    "paper_grading_protect_job_snapshot",
    "paper_grading_reject_history_mutation",
    "paper_grading_require_running_attempt_insert",
    "paper_grading_protect_attempt_history",
    "paper_grading_validate_attempt_score",
    "paper_grading_protect_review_history",
    "paper_grading_validate_review_score",
}


async def assert_statement_rejected(
    connection: AsyncConnection,
    statement: str,
    parameters: Mapping[str, Any],
) -> None:
    """确认数据库约束拒绝一次写入，并恢复到可继续测试的保存点。"""

    savepoint = await connection.begin_nested()
    try:
        with pytest.raises(DBAPIError):
            await connection.execute(text(statement), parameters)
    finally:
        if savepoint.is_active:
            await savepoint.rollback()


def test_real_database_migrations_can_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = TestMigrationSettings()
    asyncio.run(check_destructive_test_prerequisites(settings))
    monkeypatch.setenv("MIGRATION_DATABASE_URL", settings.test_migration_database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    command.upgrade(config, STAGE_TWO_REVISION)
    command.downgrade(config, STAGE_TWO_BASE_REVISION)
    command.upgrade(config, STAGE_TWO_PUBLISHED_REVISION)
    command.upgrade(config, STAGE_TWO_REVISION)

    sentinel_id = uuid4()
    asyncio.run(create_repeat_upgrade_sentinel(settings, sentinel_id))
    try:
        command.upgrade(config, STAGE_TWO_REVISION)
        asyncio.run(assert_repeat_upgrade_sentinel_exists(settings, sentinel_id))
    finally:
        asyncio.run(delete_repeat_upgrade_sentinel(settings, sentinel_id))


def test_real_database_catalog_matches_stage_two_contract() -> None:
    asyncio.run(check_database_catalog())


def test_real_database_rejects_invalid_and_cross_teacher_data() -> None:
    asyncio.run(check_database_constraints())


async def check_destructive_test_prerequisites(settings: TestMigrationSettings) -> None:
    """在任何回退前确认 Auth 用户存在且未占用阶段 2 profile。"""

    expected_user_ids = {
        settings.test_teacher_auth_user_id,
        settings.test_other_auth_user_id,
    }
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            auth_user_ids = {
                row.id
                for row in await connection.execute(
                    text("select id from auth.users where id in (:owner_id, :other_owner_id)"),
                    {
                        "owner_id": settings.test_teacher_auth_user_id,
                        "other_owner_id": settings.test_other_auth_user_id,
                    },
                )
            }
            assert auth_user_ids == expected_user_ids, "两个 Auth 测试用户必须已存在"
            profiles_exists = (
                await connection.execute(text("select to_regclass('public.profiles')"))
            ).scalar_one()
            if profiles_exists is not None:
                existing_profile_ids = {
                    row.id
                    for row in await connection.execute(
                        text("select id from profiles where id in (:owner_id, :other_owner_id)"),
                        {
                            "owner_id": settings.test_teacher_auth_user_id,
                            "other_owner_id": settings.test_other_auth_user_id,
                        },
                    )
                }
                assert existing_profile_ids == set(), "两个 Auth 测试用户不得已有 profile"
    finally:
        await engine.dispose()


async def create_repeat_upgrade_sentinel(
    settings: TestMigrationSettings,
    sentinel_id: UUID,
) -> None:
    """写入哨兵数据，验证重复升级不会破坏已有数据。"""

    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "insert into provider_configs "
                    "(id, provider_type, name, base_url) "
                    "values (:id, 'openai', :name, 'https://example.com')"
                ),
                {"id": sentinel_id, "name": f"migration-replay-{sentinel_id}"},
            )
    finally:
        await engine.dispose()


async def assert_repeat_upgrade_sentinel_exists(
    settings: TestMigrationSettings,
    sentinel_id: UUID,
) -> None:
    """确认重复升级后哨兵数据仍存在。"""

    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            count = (
                await connection.execute(
                    text("select count(*) from provider_configs where id = :id"),
                    {"id": sentinel_id},
                )
            ).scalar_one()
            assert count == 1
    finally:
        await engine.dispose()


async def delete_repeat_upgrade_sentinel(
    settings: TestMigrationSettings,
    sentinel_id: UUID,
) -> None:
    """清理重复升级验收产生的哨兵数据。"""

    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("delete from provider_configs where id = :id"),
                {"id": sentinel_id},
            )
    finally:
        await engine.dispose()


async def check_database_catalog() -> None:
    """从 PostgreSQL 系统目录确认表、约束、索引、触发器和 RLS。"""

    settings = TestMigrationSettings()
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            tables = {
                row.relname: row.relrowsecurity
                for row in (
                    await connection.execute(
                        text(
                            "select class.relname, class.relrowsecurity "
                            "from pg_class as class "
                            "join pg_namespace as namespace "
                            "on namespace.oid = class.relnamespace "
                            "where namespace.nspname = 'public' and class.relkind = 'r'"
                        )
                    )
                )
                if row.relname in EXPECTED_TABLES
            }
            constraints = {
                row.conname
                for row in await connection.execute(
                    text(
                        "select constraint_record.conname "
                        "from pg_constraint as constraint_record "
                        "join pg_class as class on class.oid = constraint_record.conrelid "
                        "join pg_namespace as namespace on namespace.oid = class.relnamespace "
                        "where namespace.nspname = 'public'"
                    )
                )
            }
            indexes = {
                row.indexname
                for row in await connection.execute(
                    text("select indexname from pg_indexes where schemaname = 'public'")
                )
            }
            triggers = {
                row.tgname
                for row in await connection.execute(
                    text(
                        "select trigger_record.tgname "
                        "from pg_trigger as trigger_record "
                        "join pg_class as class on class.oid = trigger_record.tgrelid "
                        "join pg_namespace as namespace on namespace.oid = class.relnamespace "
                        "where namespace.nspname = 'public' "
                        "and not trigger_record.tgisinternal"
                    )
                )
            }
            functions = {
                row.proname: row
                for row in await connection.execute(
                    text(
                        """
                        SELECT
                            function_record.proname,
                            function_record.proconfig,
                            function_record.prosecdef,
                            EXISTS (
                                SELECT 1
                                FROM pg_catalog.aclexplode(
                                    COALESCE(
                                        function_record.proacl,
                                        pg_catalog.acldefault(
                                            'f', function_record.proowner
                                        )
                                    )
                                ) AS privilege
                                WHERE privilege.grantee = 0
                                  AND privilege.privilege_type = 'EXECUTE'
                            ) AS public_can_execute,
                            has_function_privilege(
                                'anon', function_record.oid, 'execute'
                            ) AS anon_can_execute,
                            has_function_privilege(
                                'authenticated', function_record.oid, 'execute'
                            ) AS authenticated_can_execute,
                            has_function_privilege(
                                'service_role', function_record.oid, 'execute'
                            ) AS service_role_can_execute
                        FROM pg_proc AS function_record
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = function_record.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND function_record.proname LIKE 'paper_grading_%'
                        """
                    )
                )
            }
            rls_auto_enable = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            EXISTS (
                                SELECT 1
                                FROM pg_catalog.aclexplode(
                                    COALESCE(
                                        function_record.proacl,
                                        pg_catalog.acldefault(
                                            'f', function_record.proowner
                                        )
                                    )
                                ) AS privilege
                                WHERE privilege.grantee = 0
                                  AND privilege.privilege_type = 'EXECUTE'
                            ) AS public_can_execute,
                            has_function_privilege(
                                'anon', function_record.oid, 'execute'
                            ) AS anon_can_execute,
                            has_function_privilege(
                                'authenticated', function_record.oid, 'execute'
                            ) AS authenticated_can_execute,
                            has_function_privilege(
                                'service_role', function_record.oid, 'execute'
                            ) AS service_role_can_execute
                        FROM pg_proc AS function_record
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = function_record.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND function_record.proname = 'rls_auto_enable'
                          AND pg_get_function_identity_arguments(
                              function_record.oid
                          ) = ''
                        """
                    )
                )
            ).one_or_none()
            policies = {
                row.tablename
                for row in await connection.execute(
                    text("select tablename from pg_policies where schemaname = 'public'")
                )
                if row.tablename in EXPECTED_TABLES
            }
            migration_revision = (
                await connection.execute(text("select version_num from alembic_version"))
            ).scalar_one()
            await connection.rollback()

            visible_provider_id = uuid4()
            read_transaction = await connection.begin()
            try:
                await connection.execute(
                    text(
                        "insert into provider_configs (id, provider_type, name, base_url) "
                        "values (:id, 'openai', :name, 'https://example.com')"
                    ),
                    {"id": visible_provider_id, "name": f"rls-read-{visible_provider_id}"},
                )
                await connection.execute(text("set local role authenticated"))
                try:
                    visible_count = (
                        await connection.execute(
                            text("select count(*) from provider_configs where id = :id"),
                            {"id": visible_provider_id},
                        )
                    ).scalar_one()
                except DBAPIError:
                    ordinary_role_cannot_read = True
                else:
                    ordinary_role_cannot_read = visible_count == 0
            finally:
                await read_transaction.rollback()

            write_transaction = await connection.begin()
            try:
                await connection.execute(text("set local role authenticated"))
                try:
                    await connection.execute(
                        text(
                            "insert into provider_configs "
                            "(id, provider_type, name, base_url) "
                            "values (:id, 'openai', :name, 'https://example.com')"
                        ),
                        {"id": uuid4(), "name": f"rls-write-{uuid4()}"},
                    )
                except DBAPIError:
                    ordinary_role_cannot_write = True
                else:
                    ordinary_role_cannot_write = False
            finally:
                await write_transaction.rollback()
    finally:
        await engine.dispose()

    assert tables == dict.fromkeys(EXPECTED_TABLES, True)
    assert constraints >= EXPECTED_CONSTRAINTS
    assert indexes >= EXPECTED_INDEXES
    assert triggers >= EXPECTED_TRIGGERS
    assert functions.keys() == EXPECTED_STAGE_TWO_FUNCTIONS
    for function in functions.values():
        assert tuple(function.proconfig or ()) == ('search_path=""',)
        assert not function.prosecdef
        assert not function.public_can_execute
        assert not function.anon_can_execute
        assert not function.authenticated_can_execute
        assert not function.service_role_can_execute
    if rls_auto_enable is not None:
        assert not rls_auto_enable.public_can_execute
        assert not rls_auto_enable.anon_can_execute
        assert not rls_auto_enable.authenticated_can_execute
        assert not rls_auto_enable.service_role_can_execute
    assert policies == set()
    assert migration_revision == STAGE_TWO_REVISION
    assert ordinary_role_cannot_read
    assert ordinary_role_cannot_write


async def check_database_constraints() -> None:
    """在回滚事务内验证关键数据库约束。"""

    settings = TestMigrationSettings()
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    owner_id = settings.test_teacher_auth_user_id
    other_owner_id = settings.test_other_auth_user_id
    assignment_id = uuid4()
    rubric_id = uuid4()
    provider_id = uuid4()
    submission_id = uuid4()
    job_id = uuid4()
    item_id = uuid4()

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await assert_statement_rejected(
                connection,
                "insert into profiles (id, role, status, display_name) "
                "values (:id, 'owner', 'active', 'Invalid')",
                {"id": owner_id},
            )
            await assert_statement_rejected(
                connection,
                "insert into profiles (id, role, status, display_name) "
                "values (:id, 'teacher', 'active', 'Orphan')",
                {"id": uuid4()},
            )
            await connection.execute(
                text(
                    "insert into profiles (id, role, status, display_name) values "
                    "(:owner_id, 'teacher', 'active', 'Teacher A'), "
                    "(:other_owner_id, 'teacher', 'active', 'Teacher B')"
                ),
                {"owner_id": owner_id, "other_owner_id": other_owner_id},
            )
            await assert_statement_rejected(
                connection,
                "insert into assignments (owner_id, title, instructions) "
                "values (:owner_id, 'Essay', 'Instructions')",
                {"owner_id": uuid4()},
            )
            await connection.execute(
                text(
                    "insert into assignments (id, owner_id, title, instructions) "
                    "values (:id, :owner_id, 'Essay', 'Instructions')"
                ),
                {"id": assignment_id, "owner_id": owner_id},
            )
            await connection.execute(
                text(
                    "insert into rubric_versions "
                    "(id, owner_id, assignment_id, version, original_rubric, "
                    "structured_rubric, total_score, score_step, status, confirmed_at) "
                    "values (:id, :owner_id, :assignment_id, 1, 'Rubric', '{}'::jsonb, "
                    "100, 1, 'confirmed', now())"
                ),
                {"id": rubric_id, "owner_id": owner_id, "assignment_id": assignment_id},
            )
            await assert_statement_rejected(
                connection,
                "update rubric_versions set total_score = 200 where id = :id",
                {"id": rubric_id},
            )
            await assert_statement_rejected(
                connection,
                "insert into rubric_versions "
                "(owner_id, assignment_id, version, original_rubric, total_score, score_step) "
                "values (:owner_id, :assignment_id, 1, 'Duplicate', 100, 1)",
                {"owner_id": owner_id, "assignment_id": assignment_id},
            )
            await assert_statement_rejected(
                connection,
                "insert into rubric_versions "
                "(owner_id, assignment_id, version, original_rubric, total_score, score_step) "
                "values (:owner_id, :assignment_id, 2, 'Cross owner', 100, 1)",
                {"owner_id": other_owner_id, "assignment_id": assignment_id},
            )
            await connection.execute(
                text(
                    "insert into provider_configs "
                    "(id, provider_type, name, base_url) "
                    "values (:id, 'openai', 'test-provider', 'https://example.com')"
                ),
                {"id": provider_id},
            )
            await connection.execute(
                text(
                    "insert into submissions "
                    "(id, owner_id, assignment_id, original_filename, media_type, "
                    "file_size_bytes, content_sha256, source_object_key) "
                    "values (:id, :owner_id, :assignment_id, 'essay.pdf', "
                    "'application/pdf', 1, :hash, 'source/test')"
                ),
                {
                    "id": submission_id,
                    "owner_id": owner_id,
                    "assignment_id": assignment_id,
                    "hash": bytes(32),
                },
            )
            await assert_statement_rejected(
                connection,
                "insert into grading_jobs "
                "(owner_id, assignment_id, rubric_version_id, provider_config_id, "
                "model, model_parameters, prompt_version, prompt_hash, idempotency_key) "
                "values (:owner_id, :assignment_id, :rubric_id, :provider_id, "
                "'test-model', '[]'::jsonb, 'v1', :hash, 'invalid-json')",
                {
                    "owner_id": owner_id,
                    "assignment_id": assignment_id,
                    "rubric_id": rubric_id,
                    "provider_id": provider_id,
                    "hash": bytes(32),
                },
            )
            await connection.execute(
                text(
                    "insert into grading_jobs "
                    "(id, owner_id, assignment_id, rubric_version_id, provider_config_id, "
                    "model, prompt_version, prompt_hash, idempotency_key) "
                    "values (:id, :owner_id, :assignment_id, :rubric_id, :provider_id, "
                    "'test-model', 'v1', :hash, 'job-key')"
                ),
                {
                    "id": job_id,
                    "owner_id": owner_id,
                    "assignment_id": assignment_id,
                    "rubric_id": rubric_id,
                    "provider_id": provider_id,
                    "hash": bytes(32),
                },
            )
            await assert_statement_rejected(
                connection,
                "update grading_jobs set model = 'overwritten-model' where id = :id",
                {"id": job_id},
            )
            await connection.execute(
                text(
                    "insert into grading_job_items "
                    "(id, owner_id, assignment_id, grading_job_id, submission_id, position) "
                    "values (:id, :owner_id, :assignment_id, :job_id, :submission_id, 0)"
                ),
                {
                    "id": item_id,
                    "owner_id": owner_id,
                    "assignment_id": assignment_id,
                    "job_id": job_id,
                    "submission_id": submission_id,
                },
            )
            await assert_statement_rejected(
                connection,
                "insert into grading_attempts "
                "(owner_id, grading_job_item_id, attempt_number, status, request_hash, "
                "idempotency_key, max_score, total_score, criteria_results, "
                "overall_feedback, raw_response_object_key, finished_at) "
                "values (:owner_id, :item_id, 1, 'succeeded', :hash, 'direct-terminal', "
                "100, 90, '[]'::jsonb, 'Feedback', 'response/test', now())",
                {"owner_id": owner_id, "item_id": item_id, "hash": bytes(32)},
            )
            await assert_statement_rejected(
                connection,
                "insert into grading_attempts "
                "(owner_id, grading_job_item_id, attempt_number, request_hash, "
                "idempotency_key, max_score) "
                "values (:owner_id, :item_id, 1, :hash, 'invalid-max-score', 1000)",
                {"owner_id": owner_id, "item_id": item_id, "hash": bytes(32)},
            )
            over_total_attempt_id = uuid4()
            await connection.execute(
                text(
                    "insert into grading_attempts "
                    "(id, owner_id, grading_job_item_id, attempt_number, request_hash, "
                    "idempotency_key, max_score) "
                    "values (:id, :owner_id, :item_id, 1, :hash, 'over-total-key', 100)"
                ),
                {
                    "id": over_total_attempt_id,
                    "owner_id": owner_id,
                    "item_id": item_id,
                    "hash": bytes(32),
                },
            )
            await assert_statement_rejected(
                connection,
                "update grading_attempts set status = 'succeeded', total_score = 101, "
                "criteria_results = '[]'::jsonb, overall_feedback = 'Feedback', "
                "raw_response_object_key = 'response/test', finished_at = now() "
                "where id = :id",
                {"id": over_total_attempt_id},
            )
            attempt_id = uuid4()
            await connection.execute(
                text(
                    "insert into grading_attempts "
                    "(id, owner_id, grading_job_item_id, attempt_number, request_hash, "
                    "idempotency_key, max_score) "
                    "values (:id, :owner_id, :item_id, 2, :hash, 'valid-attempt', 100)"
                ),
                {
                    "id": attempt_id,
                    "owner_id": owner_id,
                    "item_id": item_id,
                    "hash": bytes(32),
                },
            )
            await connection.execute(
                text(
                    "update grading_attempts set status = 'succeeded', total_score = 90, "
                    "criteria_results = '[]'::jsonb, overall_feedback = 'Feedback', "
                    "raw_response_object_key = 'response/test', finished_at = now() "
                    "where id = :id"
                ),
                {"id": attempt_id},
            )
            await assert_statement_rejected(
                connection,
                "update grading_attempts set overall_feedback = 'Overwritten' where id = :id",
                {"id": attempt_id},
            )
            await assert_statement_rejected(
                connection,
                "delete from grading_attempts where id = :id",
                {"id": attempt_id},
            )
            review_id = uuid4()
            await connection.execute(
                text(
                    "insert into teacher_reviews "
                    "(id, owner_id, grading_job_item_id, grading_attempt_id, revision_number, "
                    "status, max_score, final_score, criteria_results, feedback, confirmed_at) "
                    "values (:id, :owner_id, :item_id, :attempt_id, 1, 'confirmed', 100, 90, "
                    "'[]'::jsonb, 'Confirmed', now())"
                ),
                {
                    "id": review_id,
                    "owner_id": owner_id,
                    "item_id": item_id,
                    "attempt_id": attempt_id,
                },
            )
            await assert_statement_rejected(
                connection,
                "update teacher_reviews set feedback = 'Overwritten' where id = :id",
                {"id": review_id},
            )
            await assert_statement_rejected(
                connection,
                "delete from teacher_reviews where id = :id",
                {"id": review_id},
            )
            audit_id = uuid4()
            await connection.execute(
                text(
                    "insert into audit_logs (id, owner_id, actor_id, action, resource_type) "
                    "values (:id, :owner_id, :owner_id, 'created', 'assignment')"
                ),
                {"id": audit_id, "owner_id": owner_id},
            )
            await assert_statement_rejected(
                connection,
                "update audit_logs set action = 'overwritten' where id = :id",
                {"id": audit_id},
            )
            await assert_statement_rejected(
                connection,
                "delete from audit_logs where id = :id",
                {"id": audit_id},
            )
        finally:
            await transaction.rollback()
            await engine.dispose()
