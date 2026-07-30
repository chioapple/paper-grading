"""阶段十二独立 Supabase 测试项目的导出权限与状态机目录契约。"""

import asyncio
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

from app.config import TestMigrationSettings
from app.db import Database
from app.export.models import ExportCreateInput
from app.export.repository import SqlAlchemyExportRepository
from app.export.service import ExportDataError, ExportIdempotencyConflict, ExportNotFoundError
from app.export.worker_repository import SqlAlchemyExportWorkerRepository
from app.reviews.models import ReviewConfirmationRef
from app.reviews.repository import SqlAlchemyReviewRepository
from app.workers.models import GradingJobCreate
from app.workers.repository import SqlAlchemyGradingJobRepository
from tests.test_stage10_postgres_contract import (
    build_test_database,
    seed_teacher_batch_fixture,
)
from tests.test_stage11_postgres_contract import review_data, seed_successful_attempts

STAGE_TWELVE_BASE_REVISION = "20260721_0016"
STAGE_TWELVE_REVISION = "20260722_0017"
FUNCTION_SIGNATURES = {
    "create_export": "paper_grading_private.create_export(uuid,text,text,bytea)",
    "claim_export": "paper_grading_private.claim_export(uuid,uuid,integer)",
    "complete_export": ("paper_grading_private.complete_export(uuid,uuid,text,text,bigint,bytea)"),
    "fail_export": "paper_grading_private.fail_export(uuid,uuid,text)",
}


async def read_stage_twelve_catalog(settings: TestMigrationSettings) -> dict[str, Any]:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("select version_num from alembic_version"))
            role = (
                await connection.execute(
                    text(
                        """
                        select rolcanlogin, rolinherit, rolbypassrls,
                               pg_has_role('postgres', oid, 'MEMBER') as postgres_is_member
                        from pg_catalog.pg_roles
                        where rolname = 'paper_grading_export_worker'
                        """
                    )
                )
            ).one_or_none()
            tables = {
                row.relname: row
                for row in await connection.execute(
                    text(
                        """
                        select class.relname, class.relrowsecurity, class.relforcerowsecurity
                        from pg_catalog.pg_class as class
                        join pg_catalog.pg_namespace as namespace
                          on namespace.oid = class.relnamespace
                        where namespace.nspname = 'public'
                          and class.relname in ('exports', 'export_items')
                        """
                    )
                )
            }
            functions: dict[str, Any] = {}
            for name, signature in FUNCTION_SIGNATURES.items():
                functions[name] = (
                    await connection.execute(
                        text(
                            """
                            select procedure.prosecdef,
                                   procedure.proconfig,
                                   pg_get_functiondef(procedure.oid) as definition,
                                   has_function_privilege(
                                     'paper_grading_teacher_api',
                                     cast(:signature as regprocedure), 'execute'
                                   ) as teacher_can_execute,
                                   has_function_privilege(
                                     'paper_grading_export_worker',
                                     cast(:signature as regprocedure), 'execute'
                                   ) as worker_can_execute,
                                   has_function_privilege(
                                     'anon', cast(:signature as regprocedure), 'execute'
                                   ) as anon_can_execute,
                                   has_function_privilege(
                                     'authenticated', cast(:signature as regprocedure), 'execute'
                                   ) as authenticated_can_execute,
                                   has_function_privilege(
                                     'service_role', cast(:signature as regprocedure), 'execute'
                                   ) as service_role_can_execute
                            from pg_catalog.pg_proc as procedure
                            where procedure.oid = cast(:signature as regprocedure)
                            """
                        ),
                        {"signature": signature},
                    )
                ).one()
            privileges = (
                await connection.execute(
                    text(
                        """
                        select
                          has_table_privilege(
                            'paper_grading_teacher_api', 'public.exports', 'insert'
                          ) as teacher_can_insert_exports,
                          has_table_privilege(
                            'paper_grading_teacher_api', 'public.export_items', 'select'
                          ) as teacher_can_read_items,
                          has_table_privilege(
                            'paper_grading_teacher_api', 'public.export_items',
                            'insert,update,delete'
                          ) as teacher_can_mutate_items,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.exports', 'select'
                          ) as worker_can_read_exports,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.exports', 'update'
                          ) as worker_can_update_exports,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.export_items', 'select'
                          ) as worker_can_read_items,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.export_items',
                            'insert,update,delete'
                          ) as worker_can_mutate_items,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.provider_configs', 'select'
                          ) as worker_can_read_providers,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.assignments', 'select'
                          ) as worker_can_read_assignments,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.submissions', 'select'
                          ) as worker_can_read_submissions,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.grading_attempts', 'select'
                          ) as worker_can_read_attempts,
                          has_table_privilege(
                            'paper_grading_export_worker', 'public.teacher_reviews', 'select'
                          ) as worker_can_read_reviews
                        """
                    )
                )
            ).one()
            return {
                "revision": revision,
                "role": role,
                "tables": tables,
                "functions": functions,
                "privileges": privileges,
            }
    finally:
        await engine.dispose()


@pytest.mark.postgres
def test_stage_twelve_export_roles_and_functions_are_minimal() -> None:
    settings = TestMigrationSettings()
    asyncio.run(assert_stage_twelve_migration_replay(settings))
    catalog = asyncio.run(read_stage_twelve_catalog(settings))
    assert_stage_twelve_catalog(catalog, STAGE_TWELVE_REVISION)


def assert_stage_twelve_catalog(catalog: dict[str, Any], expected_revision: str) -> None:
    assert catalog["revision"] == expected_revision
    role = cast(Any, catalog["role"])
    assert role is not None
    assert role.rolcanlogin
    assert not role.rolinherit
    assert not role.rolbypassrls
    assert role.postgres_is_member
    tables = cast(dict[str, Any], catalog["tables"])
    assert set(tables) == {"exports", "export_items"}
    assert all(row.relrowsecurity and row.relforcerowsecurity for row in tables.values())

    functions = cast(dict[str, Any], catalog["functions"])
    for function in functions.values():
        assert function.prosecdef
        assert 'search_path=""' in function.proconfig
        assert not function.anon_can_execute
        assert not function.authenticated_can_execute
        assert not function.service_role_can_execute
    assert functions["create_export"].teacher_can_execute
    assert (
        "'model_parameters', current_job.model_parameters" in functions["create_export"].definition
    )
    assert not functions["create_export"].worker_can_execute
    for name in ("claim_export", "complete_export", "fail_export"):
        assert functions[name].worker_can_execute
        assert not functions[name].teacher_can_execute

    privileges = cast(Any, catalog["privileges"])
    assert not privileges.teacher_can_insert_exports
    assert privileges.teacher_can_read_items
    assert not privileges.teacher_can_mutate_items
    assert privileges.worker_can_read_exports
    assert not privileges.worker_can_update_exports
    assert privileges.worker_can_read_items
    assert not privileges.worker_can_mutate_items
    assert not privileges.worker_can_read_providers
    assert not privileges.worker_can_read_assignments
    assert not privileges.worker_can_read_submissions
    assert not privileges.worker_can_read_attempts
    assert not privileges.worker_can_read_reviews


def build_alembic_config() -> Config:
    return Config("backend/alembic.ini")


async def run_alembic_on_connection(
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


async def assert_stage_twelve_migration_replay(settings: TestMigrationSettings) -> None:
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    config = build_alembic_config()
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("select version_num from alembic_version"))
            configured_users = await connection.scalar(
                text("select count(*) from auth.users where id = any(cast(:owner_ids as uuid[]))"),
                {
                    "owner_ids": [
                        settings.test_teacher_auth_user_id,
                        settings.test_other_auth_user_id,
                    ]
                },
            )
            if configured_users != 2:
                pytest.fail(
                    "阶段十二迁移前置检查缺少两个已配置的 Auth 用户，迁移尚未执行。",
                    pytrace=False,
                )
            await connection.commit()
            assert revision in {STAGE_TWELVE_BASE_REVISION, STAGE_TWELVE_REVISION}
            try:
                if revision == STAGE_TWELVE_REVISION:
                    await run_alembic_on_connection(
                        connection, config, command.downgrade, STAGE_TWELVE_BASE_REVISION
                    )
                await run_alembic_on_connection(
                    connection, config, command.upgrade, STAGE_TWELVE_REVISION
                )
                await connection.commit()
                await run_alembic_on_connection(
                    connection, config, command.downgrade, STAGE_TWELVE_BASE_REVISION
                )
                await run_alembic_on_connection(
                    connection, config, command.upgrade, STAGE_TWELVE_REVISION
                )
                assert (
                    await connection.scalar(text("select version_num from alembic_version"))
                    == STAGE_TWELVE_REVISION
                )
                await connection.commit()
            finally:
                if connection.in_transaction():
                    await connection.rollback()
                current = await connection.scalar(text("select version_num from alembic_version"))
                await connection.commit()
                if current != STAGE_TWELVE_REVISION:
                    await run_alembic_on_connection(
                        connection, config, command.upgrade, STAGE_TWELVE_REVISION
                    )
                    await connection.commit()
    finally:
        await engine.dispose()


async def ensure_other_teacher(connection: AsyncConnection, owner_id: UUID) -> None:
    if not await connection.scalar(
        text("select exists(select 1 from auth.users where id = :owner_id)"),
        {"owner_id": owner_id},
    ):
        pytest.fail("阶段十二权限回归缺少 TEST_OTHER_AUTH_USER_ID 对应的 Auth 用户。")
    await connection.execute(
        text(
            "insert into profiles(id, role, status, display_name) "
            "values (:owner_id, 'teacher', 'active', 'Stage Twelve Other Teacher') "
            "on conflict (id) do update set role = 'teacher', status = 'active'"
        ),
        {"owner_id": owner_id},
    )


@pytest.mark.postgres
def test_stage_twelve_snapshot_idempotency_isolation_and_worker_tokens() -> None:
    asyncio.run(assert_stage_twelve_snapshot_idempotency_isolation_and_worker_tokens())


async def assert_stage_twelve_snapshot_idempotency_isolation_and_worker_tokens() -> None:
    settings = TestMigrationSettings()
    database = build_test_database(settings)
    owner_id = settings.test_teacher_auth_user_id
    other_owner_id = settings.test_other_auth_user_id
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
                    expected_revision=STAGE_TWELVE_REVISION,
                    require_empty_grading_tables=False,
                )
                await ensure_other_teacher(connection, other_owner_id)
                grading_repository = SqlAlchemyGradingJobRepository(transactional_database)
                job = (
                    await grading_repository.create_or_get_job(
                        owner_id,
                        assignment_id,
                        GradingJobCreate(
                            submission_ids=submission_ids,
                            idempotency_key=f"stage12-job-{uuid4()}",
                        ),
                    )
                ).job
                item_ids = tuple(item.id for item in job.items)
                attempt_ids = await seed_successful_attempts(connection, owner_id, job.id, item_ids)
                review_repository = SqlAlchemyReviewRepository(transactional_database)
                first_draft = await review_repository.save_draft(
                    owner_id, item_ids[0], review_data(attempt_ids[0])
                )
                attempts_before = await connection.scalar(
                    text(
                        "select jsonb_agg(to_jsonb(attempt_row) order by attempt_row.id) "
                        "from grading_attempts as attempt_row where grading_job_id = :job_id"
                    ),
                    {"job_id": job.id},
                )
                reviews_before = await connection.scalar(
                    text(
                        "select jsonb_agg(to_jsonb(review_row) order by review_row.id) "
                        "from teacher_reviews as review_row "
                        "join grading_job_items as item_row "
                        "on item_row.id = review_row.grading_job_item_id "
                        "where item_row.grading_job_id = :job_id"
                    ),
                    {"job_id": job.id},
                )
                frozen_model_parameters = await connection.scalar(
                    text("select model_parameters from grading_jobs where id = :job_id"),
                    {"job_id": job.id},
                )
                export_repository = SqlAlchemyExportRepository(transactional_database)
                request = ExportCreateInput(grading_job_id=job.id, export_type="draft")
                key = f"stage12-export-{uuid4()}"
                first = await export_repository.create(owner_id, request, key)
                repeated = await export_repository.create(owner_id, request, key)
                assert first.created
                assert not repeated.created
                assert repeated.export.id == first.export.id
                assert first.export.source_counts == {
                    "ai_suggestion": 1,
                    "teacher_draft": 1,
                }
                assert (
                    await connection.scalar(
                        text(
                            "select jsonb_agg(to_jsonb(attempt_row) order by attempt_row.id) "
                            "from grading_attempts as attempt_row where grading_job_id = :job_id"
                        ),
                        {"job_id": job.id},
                    )
                    == attempts_before
                )
                assert (
                    await connection.scalar(
                        text(
                            "select jsonb_agg(to_jsonb(review_row) order by review_row.id) "
                            "from teacher_reviews as review_row "
                            "join grading_job_items as item_row "
                            "on item_row.id = review_row.grading_job_item_id "
                            "where item_row.grading_job_id = :job_id"
                        ),
                        {"job_id": job.id},
                    )
                    == reviews_before
                )
                with pytest.raises(ExportIdempotencyConflict):
                    await export_repository.create(
                        owner_id,
                        ExportCreateInput(grading_job_id=job.id, export_type="final"),
                        key,
                    )
                with pytest.raises(ExportDataError) as unconfirmed_final:
                    await export_repository.create(
                        owner_id,
                        ExportCreateInput(grading_job_id=job.id, export_type="final"),
                        f"unconfirmed-final-{uuid4()}",
                    )
                assert unconfirmed_final.value.code == "export_final_unconfirmed"
                with pytest.raises(ExportNotFoundError):
                    await export_repository.create(other_owner_id, request, f"other-{uuid4()}")
                other_exports = await export_repository.list(other_owner_id)
                assert first.export.id not in {item.id for item in other_exports}
                assert await export_repository.get(other_owner_id, first.export.id) is None
                assert (
                    await export_repository.get_object_key(other_owner_id, first.export.id) is None
                )

                frozen_before = (
                    await connection.execute(
                        text(
                            "select teacher_review_id, review_revision, result_snapshot "
                            "from export_items where export_id = :export_id and position = 0"
                        ),
                        {"export_id": first.export.id},
                    )
                ).one()
                metadata = await connection.scalar(
                    text("select audit_metadata from exports where id = :export_id"),
                    {"export_id": first.export.id},
                )
                assert isinstance(metadata, dict)
                assert metadata["model_parameters"] == frozen_model_parameters
                second_draft = await review_repository.save_draft(
                    owner_id, item_ids[0], review_data(attempt_ids[0])
                )
                assert second_draft.id == first_draft.id
                assert second_draft.revision_number == first_draft.revision_number + 1
                frozen_after = (
                    await connection.execute(
                        text(
                            "select teacher_review_id, review_revision, result_snapshot "
                            "from export_items where export_id = :export_id and position = 0"
                        ),
                        {"export_id": first.export.id},
                    )
                ).one()
                assert frozen_after == frozen_before

                second_item_draft = await review_repository.save_draft(
                    owner_id, item_ids[1], review_data(attempt_ids[1])
                )
                confirmed = await review_repository.confirm_reviews(
                    owner_id,
                    job.id,
                    (
                        ReviewConfirmationRef(
                            item_id=item_ids[0],
                            review_id=second_draft.id,
                            revision_number=second_draft.revision_number,
                        ),
                        ReviewConfirmationRef(
                            item_id=item_ids[1],
                            review_id=second_item_draft.id,
                            revision_number=second_item_draft.revision_number,
                        ),
                    ),
                )
                assert len(confirmed.reviews) == 2
                final_export = await export_repository.create(
                    owner_id,
                    ExportCreateInput(grading_job_id=job.id, export_type="final"),
                    f"confirmed-final-{uuid4()}",
                )
                assert final_export.export.source_counts == {"teacher_confirmed": 2}

                mutation = await connection.begin_nested()
                try:
                    with pytest.raises(DBAPIError):
                        await connection.execute(
                            text(
                                "update export_items set result_snapshot = '{}'::jsonb "
                                "where export_id = :export_id"
                            ),
                            {"export_id": first.export.id},
                        )
                finally:
                    await mutation.rollback()

                worker_repository = SqlAlchemyExportWorkerRepository(transactional_database)
                lease_token = uuid4()
                claimed = await worker_repository.claim(first.export.id, lease_token)
                assert claimed is not None
                assert await worker_repository.claim(first.export.id, uuid4()) is None
                assert not await worker_repository.complete(
                    first.export.id,
                    uuid4(),
                    object_key=f"exports/{first.export.id}/workbook.xlsx",
                    safe_filename="stage12.xlsx",
                    file_size_bytes=1,
                    file_sha256=b"x" * 32,
                )
                assert await worker_repository.complete(
                    first.export.id,
                    lease_token,
                    object_key=f"exports/{first.export.id}/workbook.xlsx",
                    safe_filename="stage12.xlsx",
                    file_size_bytes=1,
                    file_sha256=b"x" * 32,
                )
                assert not await worker_repository.fail(first.export.id, lease_token, "late_worker")
                assert await export_repository.get_object_key(owner_id, first.export.id) == (
                    f"exports/{first.export.id}/workbook.xlsx"
                )
                assert (
                    await export_repository.get_object_key(other_owner_id, first.export.id) is None
                )
            finally:
                await outer_transaction.rollback()
    finally:
        await database.dispose()


@pytest.mark.postgres
def test_stage_twelve_concurrent_worker_claim_lease_recovery_and_completion_race() -> None:
    asyncio.run(assert_concurrent_worker_claim_lease_recovery_and_completion_race())


async def assert_concurrent_worker_claim_lease_recovery_and_completion_race() -> None:
    settings = TestMigrationSettings()
    database = build_test_database(settings)
    owner_id = settings.test_teacher_auth_user_id
    export_id: UUID | None = None
    try:
        async with database.engine.connect() as setup_connection:
            setup_transaction = await setup_connection.begin()
            setup_database = Database(
                engine=database.engine,
                sessions=async_sessionmaker(
                    bind=setup_connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ),
            )
            assignment_id, submission_ids = await seed_teacher_batch_fixture(
                setup_connection,
                owner_id,
                expected_revision=STAGE_TWELVE_REVISION,
                require_empty_grading_tables=False,
            )
            grading_repository = SqlAlchemyGradingJobRepository(setup_database)
            job = (
                await grading_repository.create_or_get_job(
                    owner_id,
                    assignment_id,
                    GradingJobCreate(
                        submission_ids=submission_ids,
                        idempotency_key=f"stage12-worker-race-{uuid4()}",
                    ),
                )
            ).job
            await seed_successful_attempts(
                setup_connection,
                owner_id,
                job.id,
                tuple(item.id for item in job.items),
            )
            export = await SqlAlchemyExportRepository(setup_database).create(
                owner_id,
                ExportCreateInput(grading_job_id=job.id, export_type="draft"),
                f"stage12-worker-export-{uuid4()}",
            )
            export_id = export.export.id
            await setup_transaction.commit()

        worker = SqlAlchemyExportWorkerRepository(database)
        initial_tokens = (uuid4(), uuid4())
        initial_claims = await asyncio.gather(
            *(worker.claim(export_id, token, lease_seconds=30) for token in initial_tokens)
        )
        assert sum(claim is not None for claim in initial_claims) == 1
        initial_index = next(
            index for index, claim in enumerate(initial_claims) if claim is not None
        )
        initial_token = initial_tokens[initial_index]

        await asyncio.sleep(31)

        recovery_tokens = (uuid4(), uuid4())
        recovery_claims = await asyncio.gather(
            *(worker.claim(export_id, token, lease_seconds=30) for token in recovery_tokens)
        )
        assert sum(claim is not None for claim in recovery_claims) == 1
        recovery_index = next(
            index for index, claim in enumerate(recovery_claims) if claim is not None
        )
        recovery_token = recovery_tokens[recovery_index]
        assert not await worker.complete(
            export_id,
            initial_token,
            object_key=f"exports/{export_id}/workbook.xlsx",
            safe_filename="stage12-race.xlsx",
            file_size_bytes=1,
            file_sha256=b"r" * 32,
        )
        completion_results = await asyncio.gather(
            *(
                worker.complete(
                    export_id,
                    recovery_token,
                    object_key=f"exports/{export_id}/workbook.xlsx",
                    safe_filename="stage12-race.xlsx",
                    file_size_bytes=1,
                    file_sha256=b"r" * 32,
                )
                for _ in range(2)
            )
        )
        assert sorted(completion_results) == [False, True]
    finally:
        if export_id is not None:
            async with database.engine.begin() as cleanup_connection:
                await cleanup_connection.execute(
                    text("truncate table public.export_items, public.exports")
                )
        await database.dispose()
