"""真实 PostgreSQL 上的阶段 2 迁移与约束验收。"""

import asyncio
import os
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
EXPECTED_TABLES = {table.name for table in Base.metadata.tables.values() if table.schema is None}
EXPECTED_CONSTRAINTS = {
    str(constraint.name)
    for table in Base.metadata.tables.values()
    if table.schema is None
    for constraint in table.constraints
    if constraint.name is not None
}
EXPECTED_INDEXES = {
    str(index.name)
    for table in Base.metadata.tables.values()
    if table.schema is None
    for index in table.indexes
    if index.name is not None
}
EXPECTED_TRIGGERS = {
    "profiles_set_updated_at",
    "provider_configs_set_updated_at",
    "assignments_set_updated_at",
    "audit_logs_reject_mutation",
    "grading_attempts_protect_history",
    "teacher_reviews_protect_history",
    "grading_attempts_validate_rubric_score",
    "teacher_reviews_validate_attempt_score",
    "rubric_versions_protect_history",
    "grading_jobs_protect_snapshot",
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
    monkeypatch.setenv("MIGRATION_DATABASE_URL", settings.test_migration_database_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))

    command.upgrade(config, "head")
    command.downgrade(config, "20260713_0001")
    command.upgrade(config, "head")
    command.upgrade(config, "head")


def test_real_database_catalog_matches_stage_two_contract() -> None:
    asyncio.run(check_database_catalog())


def test_real_database_rejects_invalid_and_cross_teacher_data() -> None:
    asyncio.run(check_database_constraints())


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
            policies = {
                row.tablename
                for row in await connection.execute(
                    text("select tablename from pg_policies where schemaname = 'public'")
                )
                if row.tablename in EXPECTED_TABLES
            }
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
    assert policies == set()
    assert ordinary_role_cannot_read
    assert ordinary_role_cannot_write


async def check_database_constraints() -> None:
    """在回滚事务内验证关键数据库约束。"""

    settings = TestMigrationSettings()
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    owner_id = UUID(os.environ["TEST_TEACHER_AUTH_USER_ID"])
    other_owner_id = UUID(os.environ["TEST_OTHER_AUTH_USER_ID"])
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
                "values (:owner_id, :item_id, 1, 'succeeded', :hash, 'attempt-key', "
                "1000, 500, '[]'::jsonb, 'Feedback', 'response/test', now())",
                {"owner_id": owner_id, "item_id": item_id, "hash": bytes(32)},
            )
            await assert_statement_rejected(
                connection,
                "insert into grading_attempts "
                "(owner_id, grading_job_item_id, attempt_number, status, request_hash, "
                "idempotency_key, max_score, total_score, criteria_results, "
                "overall_feedback, raw_response_object_key, finished_at) "
                "values (:owner_id, :item_id, 1, 'succeeded', :hash, 'over-total-key', "
                "100, 101, '[]'::jsonb, 'Feedback', 'response/test', now())",
                {"owner_id": owner_id, "item_id": item_id, "hash": bytes(32)},
            )
            attempt_id = uuid4()
            await connection.execute(
                text(
                    "insert into grading_attempts "
                    "(id, owner_id, grading_job_item_id, attempt_number, status, request_hash, "
                    "idempotency_key, max_score, total_score, criteria_results, "
                    "overall_feedback, raw_response_object_key, finished_at) "
                    "values (:id, :owner_id, :item_id, 1, 'succeeded', :hash, 'valid-attempt', "
                    "100, 90, '[]'::jsonb, 'Feedback', 'response/test', now())"
                ),
                {
                    "id": attempt_id,
                    "owner_id": owner_id,
                    "item_id": item_id,
                    "hash": bytes(32),
                },
            )
            await assert_statement_rejected(
                connection,
                "update grading_attempts set overall_feedback = 'Overwritten' where id = :id",
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
                "delete from audit_logs where id = :id",
                {"id": audit_id},
            )
        finally:
            await transaction.rollback()
            await engine.dispose()
