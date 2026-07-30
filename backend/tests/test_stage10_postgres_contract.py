"""阶段十独立 Supabase 测试项目的迁移与 Worker 权限契约。"""

import asyncio
import json
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings, TestMigrationSettings
from app.db import Database
from app.workers.models import GradingJobCreate
from app.workers.repository import SqlAlchemyGradingJobRepository
from tests.auth_settings import TEST_AUTH_SETTINGS

STAGE_TEN_BASE_REVISION = "20260718_0013"
STAGE_TEN_REVISION = "20260718_0014"
EXPECTED_COLUMNS = {
    ("provider_configs", "model_profiles", "jsonb", "NO"),
    ("grading_jobs", "expected_item_count", "integer", "NO"),
    ("grading_jobs", "request_hash", "bytea", "NO"),
    ("grading_jobs", "model_parameters_hash", "bytea", "NO"),
    ("grading_jobs", "state_version", "bigint", "NO"),
    ("grading_job_items", "dispatch_version", "integer", "NO"),
    ("grading_job_items", "lease_token", "uuid", "YES"),
    ("grading_attempts", "attempt_kind", "text", "NO"),
    ("grading_attempts", "provider_call_state", "text", "NO"),
    ("grading_attempts", "input_tokens", "bigint", "YES"),
    ("grading_attempts", "estimated_cost_amount", "numeric", "YES"),
}
EXPECTED_INDEXES = {
    "grading_job_items_dispatch_idx",
    "grading_job_items_expired_lease_idx",
    "grading_attempts_one_running_idx",
    "grading_attempts_raw_response_object_key_idx",
}
EXPECTED_WORKER_POLICIES = {
    "provider_configs_worker_all",
    "assignments_worker_all",
    "rubric_versions_worker_all",
    "submissions_worker_all",
    "grading_jobs_worker_all",
    "grading_job_items_worker_all",
    "grading_attempts_worker_all",
}
TEST_MODEL = "deepseek-chat"
TEST_MODEL_PROFILE = {
    "capabilities": {
        "capability_version": "stage10-permission-regression.v1",
        "model": TEST_MODEL,
        "context_window_tokens": 128000,
        "max_output_tokens": 8192,
        "structured_output": "json_object",
        "schema_dialect": "canonical",
        "sampling_policy": "temperature_zero",
        "thinking_policy": "disabled",
        "output_token_parameter": "max_tokens",
        "supports_model_listing": True,
        "pricing": None,
    },
    "grading_max_output_tokens": 4096,
}
TEST_STRUCTURED_RUBRIC = {
    "schema_version": 1,
    "total_score": "10",
    "score_step": "1",
    "dimensions": [
        {
            "id": "content",
            "name": "Content",
            "description": "Evaluate the response content.",
            "max_score": "10",
            "bands": [
                {
                    "label": "Full range",
                    "min_score": "0",
                    "max_score": "10",
                    "description": "Use the full score range.",
                }
            ],
            "evidence_requirements": ["Quote exact evidence."],
        }
    ],
    "deductions": [],
}


def build_alembic_config() -> Config:
    return Config("backend/alembic.ini")


async def run_alembic_on_connection(
    connection: AsyncConnection,
    config: Config,
    operation: Callable[[Config, str], None],
    revision: str,
) -> None:
    """让 Alembic 在验收已建立的 direct 连接中执行迁移。"""

    if connection.in_transaction():
        raise RuntimeError("Alembic 迁移前必须结束调用方事务")

    def invoke(sync_connection: Connection) -> None:
        config.attributes["connection"] = sync_connection
        try:
            operation(config, revision)
        finally:
            config.attributes.pop("connection", None)

    await connection.run_sync(invoke)


def test_alembic_replay_reuses_the_caller_connection() -> None:
    """迁移回放不得为每一步重新建立 direct SSL 连接。"""

    supplied_connection = object()

    class FakeAsyncConnection:
        def in_transaction(self) -> bool:
            return False

        async def run_sync(self, function: Callable[[Any], None]) -> None:
            function(supplied_connection)

    config = build_alembic_config()
    observed: list[tuple[object, str]] = []

    def operation(operation_config: Config, revision: str) -> None:
        observed.append((operation_config.attributes["connection"], revision))

    asyncio.run(
        run_alembic_on_connection(
            cast(AsyncConnection, FakeAsyncConnection()),
            config,
            operation,
            STAGE_TEN_REVISION,
        )
    )

    assert observed == [(supplied_connection, STAGE_TEN_REVISION)]
    assert "connection" not in config.attributes


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


async def seed_teacher_batch_fixture(
    connection: AsyncConnection,
    owner_id: UUID,
    *,
    expected_revision: str = STAGE_TEN_REVISION,
    require_empty_grading_tables: bool = True,
) -> tuple[UUID, tuple[UUID, UUID]]:
    """在调用方外层事务中准备数据，最终只回滚，不执行历史删除。"""

    provider_id = uuid4()
    assignment_id = uuid4()
    rubric_id = uuid4()
    submission_ids = (uuid4(), uuid4())

    revision = await connection.scalar(text("select version_num from public.alembic_version"))
    assert revision == expected_revision
    if require_empty_grading_tables:
        grading_counts = (
            await connection.execute(
                text(
                    "select "
                    "(select count(*) from public.grading_jobs) as jobs, "
                    "(select count(*) from public.grading_job_items) as items, "
                    "(select count(*) from public.grading_attempts) as attempts"
                )
            )
        ).one()
        if (grading_counts.jobs, grading_counts.items, grading_counts.attempts) != (0, 0, 0):
            pytest.fail(
                "阶段十权限回归要求三张评分表在开始前均为空，已停止且未修改现有数据。",
                pytrace=False,
            )
    auth_user_exists = await connection.scalar(
        text("select exists(select 1 from auth.users where id = :owner_id)"),
        {"owner_id": owner_id},
    )
    if not auth_user_exists:
        pytest.fail(
            "阶段十权限回归缺少 TEST_TEACHER_AUTH_USER_ID 对应的 Auth 用户。",
            pytrace=False,
        )

    profile = (
        await connection.execute(
            text("select role, status from public.profiles where id = :owner_id"),
            {"owner_id": owner_id},
        )
    ).one_or_none()
    if profile is None:
        await connection.execute(
            text(
                "insert into public.profiles (id, role, status, display_name) "
                "values (:owner_id, 'teacher', 'active', 'Stage Ten Permission Teacher')"
            ),
            {"owner_id": owner_id},
        )
    elif (profile.role, profile.status) != ("teacher", "active"):
        pytest.fail(
            "TEST_TEACHER_AUTH_USER_ID 必须对应 active teacher profile。",
            pytrace=False,
        )

    await connection.execute(
        text(
            "insert into public.provider_configs ("
            "id, provider_type, name, base_url, encrypted_api_key, api_key_nonce, "
            "allowed_models, default_model, model_profiles, status, config_version, "
            "tested_config_version, tested_at) values ("
            ":provider_id, 'deepseek', :name, 'https://api.deepseek.com', "
            ":encrypted_api_key, :api_key_nonce, cast(:allowed_models as jsonb), :model, "
            "cast(:model_profiles as jsonb), 'enabled', 1, 1, now())"
        ),
        {
            "provider_id": provider_id,
            "name": f"Stage Ten Permission {provider_id}",
            "encrypted_api_key": bytes(range(17)),
            "api_key_nonce": bytes(range(12)),
            "allowed_models": json.dumps([TEST_MODEL]),
            "model": TEST_MODEL,
            "model_profiles": json.dumps({TEST_MODEL: TEST_MODEL_PROFILE}),
        },
    )
    await connection.execute(
        text(
            "insert into public.assignments (id, owner_id, title, instructions, status) "
            "values (:assignment_id, :owner_id, 'Stage Ten Permission', "
            "'Grade the submitted essay.', 'draft')"
        ),
        {"assignment_id": assignment_id, "owner_id": owner_id},
    )
    await connection.execute(
        text(
            "insert into public.rubric_versions ("
            "id, owner_id, assignment_id, provider_config_id, model, version, status, "
            "original_rubric, structured_rubric, total_score, score_step, confirmed_at) "
            "values (:rubric_id, :owner_id, :assignment_id, :provider_id, :model, 1, "
            "'confirmed', 'Stage ten permission rubric', cast(:structured_rubric as jsonb), "
            "10, 1, now())"
        ),
        {
            "rubric_id": rubric_id,
            "owner_id": owner_id,
            "assignment_id": assignment_id,
            "provider_id": provider_id,
            "model": TEST_MODEL,
            "structured_rubric": json.dumps(TEST_STRUCTURED_RUBRIC),
        },
    )
    await connection.execute(
        text(
            "update public.assignments set status = 'ready' "
            "where id = :assignment_id and owner_id = :owner_id"
        ),
        {"assignment_id": assignment_id, "owner_id": owner_id},
    )
    submission_rows = []
    for position, submission_id in enumerate(submission_ids, start=1):
        base_path = f"teachers/{owner_id}/assignments/{assignment_id}/submissions/{submission_id}"
        submission_rows.append(
            {
                "submission_id": submission_id,
                "owner_id": owner_id,
                "assignment_id": assignment_id,
                "filename": f"permission-regression-{position}.pdf",
                "content_sha256": position.to_bytes(32, "big"),
                "source_object_key": f"{base_path}/source.pdf",
                "extracted_object_key": f"{base_path}/document-blocks.v1.json",
            }
        )
    await connection.execute(
        text(
            "insert into public.submissions ("
            "id, owner_id, assignment_id, original_filename, media_type, file_size_bytes, "
            "content_sha256, source_object_key, extracted_object_key, status) values ("
            ":submission_id, :owner_id, :assignment_id, :filename, 'application/pdf', 1, "
            ":content_sha256, :source_object_key, :extracted_object_key, 'ready')"
        ),
        submission_rows,
    )
    return assignment_id, submission_ids


async def read_stage_ten_catalog(connection: AsyncConnection) -> dict[str, object]:
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
                select 'grading_job_items', count(*)
                from public.grading_job_items
                union all
                select 'grading_attempts', count(*)
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
                  and (table_name, column_name) in (
                    ('provider_configs', 'model_profiles'),
                    ('grading_jobs', 'expected_item_count'),
                    ('grading_jobs', 'request_hash'),
                    ('grading_jobs', 'model_parameters_hash'),
                    ('grading_jobs', 'state_version'),
                    ('grading_job_items', 'dispatch_version'),
                    ('grading_job_items', 'lease_token'),
                    ('grading_attempts', 'attempt_kind'),
                    ('grading_attempts', 'provider_call_state'),
                    ('grading_attempts', 'input_tokens'),
                    ('grading_attempts', 'estimated_cost_amount')
                  )
                """
            )
        )
    }
    indexes = {
        row.indexname
        for row in await connection.execute(
            text(
                """
                select indexname
                from pg_catalog.pg_indexes
                where schemaname = 'public'
                  and indexname in (
                    'grading_job_items_dispatch_idx',
                    'grading_job_items_expired_lease_idx',
                    'grading_attempts_one_running_idx',
                    'grading_attempts_raw_response_object_key_idx'
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
                       function_record.prosecdef,
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
                         'paper_grading_teacher_api', function_record.oid, 'execute'
                       ) as teacher_api_can_execute
                from pg_catalog.pg_proc as function_record
                join pg_catalog.pg_namespace as namespace
                  on namespace.oid = function_record.pronamespace
                where (namespace.nspname, function_record.proname) in (
                  ('public', 'paper_grading_require_ready_job_item'),
                  ('public', 'paper_grading_protect_job_snapshot'),
                  ('public', 'paper_grading_protect_job_item'),
                  ('public', 'paper_grading_protect_attempt_history'),
                  ('public', 'paper_grading_validate_job_item_count'),
                  ('paper_grading_private', 'control_grading_job')
                )
                """
            )
        )
    }
    worker = (
        await connection.execute(
            text(
                """
                select role.rolcanlogin,
                       role.rolbypassrls,
                       pg_has_role('postgres', role.oid, 'MEMBER') as postgres_is_member,
                       has_table_privilege(
                         'paper_grading_worker', 'public.grading_jobs', 'select, update'
                       ) as can_update_jobs,
                       has_table_privilege(
                         'paper_grading_worker', 'public.grading_attempts',
                         'select, insert, update'
                       ) as can_write_attempts,
                       has_table_privilege(
                         'paper_grading_worker', 'public.provider_configs', 'update'
                       ) as can_update_providers,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.submissions', 'update'
                       ) as teacher_can_update_submissions,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.submissions', 'update'
                       ) as teacher_can_update_submission_columns,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
                       ) as teacher_can_update_jobs,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
                       ) as teacher_can_update_job_columns,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
                       ) as teacher_can_update_items,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
                       ) as teacher_can_update_item_columns
                from pg_catalog.pg_roles as role
                where role.rolname = 'paper_grading_worker'
                """
            )
        )
    ).one_or_none()
    policies = {
        row.policyname
        for row in await connection.execute(
            text(
                """
                select policyname
                from pg_catalog.pg_policies
                where schemaname = 'public'
                  and 'paper_grading_worker' = any(roles)
                """
            )
        )
    }
    return {
        "revision": revision,
        "counts": counts,
        "columns": columns,
        "indexes": indexes,
        "functions": functions,
        "worker": worker,
        "policies": policies,
    }


async def assert_test_teacher_preflight(
    connection: AsyncConnection,
    owner_id: UUID,
) -> None:
    """迁移前确认测试教师可用，避免升级后才暴露配置错误。"""

    teacher = (
        await connection.execute(
            text(
                "select "
                "exists(select 1 from auth.users where id = :owner_id) "
                "as auth_user_exists, "
                "(select role from public.profiles where id = :owner_id) "
                "as profile_role, "
                "(select status from public.profiles where id = :owner_id) "
                "as profile_status"
            ),
            {"owner_id": owner_id},
        )
    ).one()
    if not teacher.auth_user_exists:
        pytest.fail(
            "TEST_TEACHER_AUTH_USER_ID 在 auth.users 中不存在，迁移尚未执行。",
            pytrace=False,
        )
    if teacher.profile_role is not None and (
        teacher.profile_role,
        teacher.profile_status,
    ) != ("teacher", "active"):
        pytest.fail(
            "现有 TEST_TEACHER_AUTH_USER_ID profile 必须是 active teacher，迁移尚未执行。",
            pytrace=False,
        )


def assert_stage_ten_catalog(
    catalog: dict[str, object],
    expected_revision: str = STAGE_TEN_REVISION,
    *,
    expected_worker_login: bool = False,
    require_empty_grading_tables: bool = True,
) -> None:
    assert catalog["revision"] == expected_revision
    if require_empty_grading_tables:
        assert catalog["counts"] == {
            "grading_jobs": 0,
            "grading_job_items": 0,
            "grading_attempts": 0,
        }
    assert catalog["columns"] == EXPECTED_COLUMNS
    assert catalog["indexes"] == EXPECTED_INDEXES
    assert catalog["policies"] == EXPECTED_WORKER_POLICIES

    functions = cast(dict[str, Any], catalog["functions"])
    assert set(functions) == {
        "paper_grading_require_ready_job_item",
        "paper_grading_protect_job_snapshot",
        "paper_grading_protect_job_item",
        "paper_grading_protect_attempt_history",
        "paper_grading_validate_job_item_count",
        "control_grading_job",
    }
    for name, function in functions.items():
        assert tuple(function.proconfig or ()) == ('search_path=""',)
        assert not function.public_can_execute
        assert function.prosecdef is (name == "control_grading_job")
    assert functions["control_grading_job"].teacher_api_can_execute
    permission_guard = functions["paper_grading_require_ready_job_item"].definition.upper()
    assert "FOR UPDATE" not in permission_guard
    assert "FOR SHARE" not in permission_guard
    count_guard = functions["paper_grading_validate_job_item_count"].definition.upper()
    assert "IF TG_TABLE_NAME = 'GRADING_JOBS' THEN" in count_guard
    assert "ELSIF TG_TABLE_NAME = 'GRADING_JOB_ITEMS' THEN" in count_guard
    assert "ELSE NEW.GRADING_JOB_ID" not in count_guard
    assert (
        "config_version = current_job.provider_config_version"
        in functions["control_grading_job"].definition
    )

    worker = cast(Any, catalog["worker"])
    assert worker is not None
    assert worker.rolcanlogin is expected_worker_login
    assert not worker.rolbypassrls
    assert worker.postgres_is_member
    assert worker.can_update_jobs
    assert worker.can_write_attempts
    assert not worker.can_update_providers
    assert not worker.teacher_can_update_submissions
    assert not worker.teacher_can_update_submission_columns
    assert not worker.teacher_can_update_jobs
    assert not worker.teacher_can_update_job_columns
    assert not worker.teacher_can_update_items
    assert not worker.teacher_can_update_item_columns


@pytest.mark.postgres
def test_stage_ten_batch_pipeline_replays_on_real_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只在用户显式运行时执行可重跑的 0013→0014→0013→0014。"""

    settings = TestMigrationSettings()
    monkeypatch.setenv("MIGRATION_DATABASE_URL", settings.test_migration_database_url)
    config = build_alembic_config()
    asyncio.run(assert_stage_ten_migration_replay(settings, config))


async def assert_stage_ten_migration_replay(
    settings: TestMigrationSettings,
    config: Config,
) -> None:
    """用一个 direct SSL 连接完成全部回放和目录核验。"""

    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await assert_test_teacher_preflight(
                connection,
                settings.test_teacher_auth_user_id,
            )
            before = await read_stage_ten_catalog(connection)
            await connection.commit()
            assert before["revision"] in {STAGE_TEN_BASE_REVISION, STAGE_TEN_REVISION}
            assert before["counts"] == {
                "grading_jobs": 0,
                "grading_job_items": 0,
                "grading_attempts": 0,
            }
            try:
                if before["revision"] == STAGE_TEN_REVISION:
                    await run_alembic_on_connection(
                        connection,
                        config,
                        command.downgrade,
                        STAGE_TEN_BASE_REVISION,
                    )
                baseline = await read_stage_ten_catalog(connection)
                await connection.commit()
                assert baseline["revision"] == STAGE_TEN_BASE_REVISION
                assert baseline["counts"] == before["counts"]

                await run_alembic_on_connection(
                    connection,
                    config,
                    command.upgrade,
                    STAGE_TEN_REVISION,
                )
                upgraded = await read_stage_ten_catalog(connection)
                await connection.commit()
                assert_stage_ten_catalog(upgraded)
                await run_alembic_on_connection(
                    connection,
                    config,
                    command.downgrade,
                    STAGE_TEN_BASE_REVISION,
                )
                rolled_back = await read_stage_ten_catalog(connection)
                await connection.commit()
                assert rolled_back["revision"] == STAGE_TEN_BASE_REVISION
                assert rolled_back["counts"] == {
                    "grading_jobs": 0,
                    "grading_job_items": 0,
                    "grading_attempts": 0,
                }
                await run_alembic_on_connection(
                    connection,
                    config,
                    command.upgrade,
                    STAGE_TEN_REVISION,
                )
                final = await read_stage_ten_catalog(connection)
                await connection.commit()
                assert_stage_ten_catalog(final)
            finally:
                if connection.in_transaction():
                    await connection.rollback()
                current_revision = await connection.scalar(
                    text("select version_num from alembic_version")
                )
                await connection.commit()
                if current_revision != STAGE_TEN_REVISION:
                    await run_alembic_on_connection(
                        connection,
                        config,
                        command.upgrade,
                        STAGE_TEN_REVISION,
                    )
                restored_revision = await connection.scalar(
                    text("select version_num from alembic_version")
                )
                await connection.commit()
                assert restored_revision == STAGE_TEN_REVISION
    finally:
        await engine.dispose()


@pytest.mark.postgres
def test_teacher_creates_idempotent_batch_without_update_privileges() -> None:
    """真实教师角色能创建批次，但仍不能直接更新论文或任务表。"""

    asyncio.run(assert_teacher_batch_permission_contract())


async def assert_teacher_batch_permission_contract(
    expected_revision: str = STAGE_TEN_REVISION,
) -> None:
    settings = TestMigrationSettings()
    database = build_test_database(settings)
    owner_id = settings.test_teacher_auth_user_id
    try:
        async with database.engine.connect() as connection:
            outer_transaction = await connection.begin()
            transactional_database = Database(
                engine=database.engine,
                sessions=async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ),
            )
            try:
                assignment_id, submission_ids = await seed_teacher_batch_fixture(
                    connection,
                    owner_id,
                    expected_revision=expected_revision,
                )
                repository = SqlAlchemyGradingJobRepository(transactional_database)
                payload = GradingJobCreate(
                    submission_ids=submission_ids,
                    idempotency_key=f"stage10-permission-{uuid4()}",
                )

                created = await repository.create_or_get_job(owner_id, assignment_id, payload)
                repeated = await repository.create_or_get_job(owner_id, assignment_id, payload)

                assert created.created
                assert not repeated.created
                assert repeated.job.id == created.job.id
                assert created.job.total == 2
                assert created.job.queued == 2
                assert [item.position for item in created.job.items] == [0, 1]
                assert {item.submission_id for item in created.job.items} == set(submission_ids)

                await connection.execute(
                    text(
                        "set constraints grading_jobs_validate_item_count, "
                        "grading_job_items_validate_job_count immediate"
                    )
                )

                await connection.execute(text("set local role none"))
                privileges = (
                    await connection.execute(
                        text(
                            "select "
                            "has_table_privilege('paper_grading_teacher_api', "
                            "'public.submissions', 'update') as submissions_update, "
                            "has_any_column_privilege('paper_grading_teacher_api', "
                            "'public.submissions', 'update') as submissions_column_update, "
                            "has_table_privilege('paper_grading_teacher_api', "
                            "'public.grading_jobs', 'update') as jobs_update, "
                            "has_any_column_privilege('paper_grading_teacher_api', "
                            "'public.grading_jobs', 'update') as jobs_column_update, "
                            "has_table_privilege('paper_grading_teacher_api', "
                            "'public.grading_job_items', 'update') as items_update, "
                            "has_any_column_privilege('paper_grading_teacher_api', "
                            "'public.grading_job_items', 'update') as items_column_update"
                        )
                    )
                ).one()
                assert not privileges.submissions_update
                assert not privileges.submissions_column_update
                assert not privileges.jobs_update
                assert not privileges.jobs_column_update
                assert not privileges.items_update
                assert not privileges.items_column_update

                denied_updates = (
                    (
                        text("update public.submissions set status = status where id = :row_id"),
                        submission_ids[0],
                    ),
                    (
                        text("update public.grading_jobs set status = status where id = :row_id"),
                        created.job.id,
                    ),
                    (
                        text(
                            "update public.grading_job_items set status = status where id = :row_id"
                        ),
                        created.job.items[0].id,
                    ),
                )
                claims = json.dumps(
                    {"sub": str(owner_id), "role": "authenticated"},
                    separators=(",", ":"),
                )
                for update_statement, row_id in denied_updates:
                    with pytest.raises(DBAPIError) as denied:
                        async with (
                            transactional_database.sessions() as session,
                            session.begin(),
                        ):
                            await session.execute(
                                text("select set_config('request.jwt.claims', :claims, true)"),
                                {"claims": claims},
                            )
                            await session.execute(text("set local role paper_grading_teacher_api"))
                            await session.execute(update_statement, {"row_id": row_id})
                    assert getattr(denied.value.orig, "sqlstate", None) == "42501"
            finally:
                await outer_transaction.rollback()
    finally:
        await database.dispose()
