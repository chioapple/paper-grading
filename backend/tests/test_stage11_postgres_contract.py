"""阶段十一独立 Supabase 测试项目的迁移、权限和原子确认契约。"""

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

from app.config import TestMigrationSettings
from app.db import Database
from app.reviews.models import (
    ReviewConfirmationRef,
    ReviewCriterionInput,
    ReviewDraftData,
    ReviewEvidenceInput,
)
from app.reviews.repository import SqlAlchemyReviewRepository
from app.reviews.service import ReviewNotFoundError
from app.workers.models import GradingJobCreate
from app.workers.repository import SqlAlchemyGradingJobRepository
from tests.test_stage10_postgres_contract import (
    TEST_MODEL,
    build_test_database,
    seed_teacher_batch_fixture,
)

STAGE_TEN_REVISION = "20260718_0014"
STAGE_ELEVEN_SCHEMA_REVISION = "20260719_0015"
STAGE_ELEVEN_REVISION = "20260721_0016"
ATTEMPT_CRITERIA = [
    {
        "dimension_id": "content",
        "score": "8",
        "reason": "The response addresses the task.",
        "evidence": [{"block_id": "b000001", "quote": "Exact evidence"}],
        "revision_suggestions": ["Add a fuller explanation."],
    }
]


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


async def read_stage_eleven_catalog(connection: AsyncConnection) -> dict[str, object]:
    functions = {
        row.proname: row
        for row in await connection.execute(
            text(
                """
                select function_record.proname,
                       function_record.proconfig,
                       function_record.prosecdef,
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
                       ) as teacher_can_execute,
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
                where namespace.nspname = 'paper_grading_private'
                  and function_record.proname in (
                    'save_teacher_review_draft',
                    'confirm_teacher_reviews',
                    'validate_teacher_review_payload'
                  )
                """
            )
        )
    }
    privileges = (
        await connection.execute(
            text(
                """
                select has_table_privilege(
                         'paper_grading_teacher_api', 'public.teacher_reviews', 'insert'
                       ) as reviews_insert,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.teacher_reviews', 'update'
                       ) as reviews_update,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
                       ) as jobs_update,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
                       ) as items_update,
                       has_table_privilege(
                         'paper_grading_teacher_api', 'public.audit_logs', 'insert'
                       ) as audit_insert,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.teacher_reviews', 'insert'
                       ) as reviews_column_insert,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.teacher_reviews', 'update'
                       ) as reviews_column_update,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.grading_jobs', 'update'
                       ) as jobs_column_update,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.grading_job_items', 'update'
                       ) as items_column_update,
                       has_any_column_privilege(
                         'paper_grading_teacher_api', 'public.audit_logs', 'insert'
                       ) as audit_column_insert
                """
            )
        )
    ).one()
    columns = {
        (row.column_name, row.data_type, row.is_nullable)
        for row in await connection.execute(
            text(
                """
                select column_name, data_type, is_nullable
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'teacher_reviews'
                  and column_name in (
                    'deduction_results', 'subtotal', 'deduction_total',
                    'final_score', 'criteria_results', 'feedback'
                  )
                """
            )
        )
    }
    return {
        "revision": await connection.scalar(text("select version_num from alembic_version")),
        "review_count": await connection.scalar(text("select count(*) from teacher_reviews")),
        "columns": columns,
        "functions": functions,
        "privileges": privileges,
        "attempt_index": await connection.scalar(
            text(
                "select indexdef from pg_indexes where schemaname = 'public' "
                "and indexname = 'teacher_reviews_one_attempt_idx'"
            )
        ),
    }


def assert_stage_eleven_catalog(catalog: dict[str, object]) -> None:
    assert catalog["revision"] == STAGE_ELEVEN_REVISION
    assert catalog["columns"] == {
        ("deduction_results", "jsonb", "NO"),
        ("subtotal", "numeric", "NO"),
        ("deduction_total", "numeric", "NO"),
        ("final_score", "numeric", "NO"),
        ("criteria_results", "jsonb", "NO"),
        ("feedback", "text", "NO"),
    }
    attempt_index = cast(str, catalog["attempt_index"])
    assert "CREATE UNIQUE INDEX teacher_reviews_one_attempt_idx" in attempt_index
    assert "(grading_attempt_id)" in attempt_index
    functions = cast(dict[str, Any], catalog["functions"])
    assert set(functions) == {
        "save_teacher_review_draft",
        "confirm_teacher_reviews",
        "validate_teacher_review_payload",
    }
    for function in functions.values():
        assert tuple(function.proconfig or ()) == ('search_path=""',)
        assert function.prosecdef
        assert not function.public_can_execute
        assert not function.anon_can_execute
        assert not function.authenticated_can_execute
        assert not function.service_role_can_execute
    assert functions["save_teacher_review_draft"].teacher_can_execute
    assert functions["confirm_teacher_reviews"].teacher_can_execute
    assert not functions["validate_teacher_review_payload"].teacher_can_execute
    privileges = cast(Any, catalog["privileges"])
    assert not privileges.reviews_insert
    assert not privileges.reviews_update
    assert not privileges.jobs_update
    assert not privileges.items_update
    assert not privileges.audit_insert
    assert not privileges.reviews_column_insert
    assert not privileges.reviews_column_update
    assert not privileges.jobs_column_update
    assert not privileges.items_column_update
    assert not privileges.audit_column_insert


@pytest.mark.postgres
def test_stage_eleven_migration_replays_on_real_supabase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = TestMigrationSettings()
    monkeypatch.setenv("MIGRATION_DATABASE_URL", settings.test_migration_database_url)
    asyncio.run(assert_stage_eleven_migration_replay(settings, build_alembic_config()))


async def assert_stage_eleven_migration_replay(
    settings: TestMigrationSettings,
    config: Config,
) -> None:
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            before = await read_stage_eleven_catalog(connection)
            await connection.commit()
            assert before["revision"] in {
                STAGE_ELEVEN_SCHEMA_REVISION,
                STAGE_ELEVEN_REVISION,
            }
            try:
                if before["revision"] == STAGE_ELEVEN_REVISION:
                    await run_alembic_on_connection(
                        connection, config, command.downgrade, STAGE_ELEVEN_SCHEMA_REVISION
                    )
                assert (
                    await connection.scalar(text("select version_num from alembic_version"))
                    == STAGE_ELEVEN_SCHEMA_REVISION
                )
                await connection.commit()
                await run_alembic_on_connection(
                    connection, config, command.upgrade, STAGE_ELEVEN_REVISION
                )
                assert_stage_eleven_catalog(await read_stage_eleven_catalog(connection))
                await connection.commit()
                await run_alembic_on_connection(
                    connection, config, command.downgrade, STAGE_ELEVEN_SCHEMA_REVISION
                )
                assert (
                    await connection.scalar(text("select version_num from alembic_version"))
                    == STAGE_ELEVEN_SCHEMA_REVISION
                )
                await connection.commit()
                await run_alembic_on_connection(
                    connection, config, command.upgrade, STAGE_ELEVEN_REVISION
                )
                assert_stage_eleven_catalog(await read_stage_eleven_catalog(connection))
                await connection.commit()
            finally:
                if connection.in_transaction():
                    await connection.rollback()
                revision = await connection.scalar(text("select version_num from alembic_version"))
                await connection.commit()
                if revision != STAGE_ELEVEN_REVISION:
                    await run_alembic_on_connection(
                        connection, config, command.upgrade, STAGE_ELEVEN_REVISION
                    )
                assert (
                    await connection.scalar(text("select version_num from alembic_version"))
                    == STAGE_ELEVEN_REVISION
                )
                await connection.commit()
    finally:
        await engine.dispose()


async def seed_successful_attempts(
    connection: AsyncConnection,
    owner_id: UUID,
    job_id: UUID,
    item_ids: tuple[UUID, ...],
    *,
    job_status: str = "needs_review",
) -> tuple[UUID, ...]:
    await connection.execute(text("set local role paper_grading_worker"))
    await connection.execute(
        text("update grading_jobs set status = 'running', started_at = now() where id = :job_id"),
        {"job_id": job_id},
    )
    attempt_ids: list[UUID] = []
    for index, item_id in enumerate(item_ids, start=1):
        attempt_id = uuid4()
        attempt_ids.append(attempt_id)
        lease_token = uuid4()
        await connection.execute(
            text(
                "update grading_job_items set status = 'running', started_at = now(), "
                "lease_token = :lease_token, lease_expires_at = now() + interval '5 minutes' "
                "where id = :item_id"
            ),
            {"item_id": item_id, "lease_token": lease_token},
        )
        await connection.execute(
            text(
                "insert into grading_attempts ("
                "id, owner_id, grading_job_item_id, attempt_number, scoring_round, "
                "call_sequence, attempt_kind, status, provider_call_started_at, "
                "provider_call_state, request_version, request_hash, idempotency_key, max_score) "
                "values (:attempt_id, :owner_id, :item_id, 1, 1, 1, 'initial', 'running', "
                "now(), 'started', 'grade-request.v1', :request_hash, :idempotency_key, 10)"
            ),
            {
                "attempt_id": attempt_id,
                "owner_id": owner_id,
                "item_id": item_id,
                "request_hash": index.to_bytes(32, "big"),
                "idempotency_key": f"stage11-attempt-{attempt_id}",
            },
        )
        await connection.execute(
            text(
                "update grading_attempts set status = 'succeeded', "
                "provider_call_state = 'response_received', total_score = 8, subtotal = 8, "
                "deduction_total = 0, criteria_results = cast(:criteria as jsonb), "
                "deduction_results = '[]'::jsonb, overall_feedback = :feedback, "
                "raw_response_object_key = :raw_key, raw_response_sha256 = :raw_hash, "
                "provider_request_id = :request_id, reported_model = :model, "
                "input_tokens = 10, cached_input_tokens = 0, cache_write_input_tokens = 0, "
                "output_tokens = 10, reasoning_tokens = 0, total_tokens = 20, finished_at = now() "
                "where id = :attempt_id"
            ),
            {
                "attempt_id": attempt_id,
                "criteria": json.dumps(ATTEMPT_CRITERIA),
                "feedback": "A clear response with room for fuller explanation.",
                "raw_key": f"stage11/raw/{attempt_id}.json",
                "raw_hash": (index + 10).to_bytes(32, "big"),
                "request_id": f"stage11-request-{attempt_id}",
                "model": TEST_MODEL,
            },
        )
        await connection.execute(
            text(
                "update grading_job_items set status = 'needs_review', finished_at = now(), "
                "lease_token = null, lease_expires_at = null where id = :item_id"
            ),
            {"item_id": item_id},
        )
    await connection.execute(
        text("update grading_jobs set status = :job_status where id = :job_id"),
        {"job_id": job_id, "job_status": job_status},
    )
    await connection.execute(text("set local role none"))
    return tuple(attempt_ids)


@pytest.mark.postgres
def test_partial_confirmation_keeps_queued_item_dispatchable() -> None:
    asyncio.run(assert_partial_confirmation_keeps_queued_item_dispatchable())


async def assert_partial_confirmation_keeps_queued_item_dispatchable() -> None:
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
                await connection.execute(text("set local role none"))
                assert (
                    await connection.scalar(text("select version_num from alembic_version"))
                    == STAGE_ELEVEN_REVISION
                )
                assignment_id, submission_ids = await seed_teacher_batch_fixture(
                    connection,
                    owner_id,
                    expected_revision=STAGE_ELEVEN_REVISION,
                    require_empty_grading_tables=False,
                )
                grading_repository = SqlAlchemyGradingJobRepository(transactional_database)
                creation = await grading_repository.create_or_get_job(
                    owner_id,
                    assignment_id,
                    GradingJobCreate(
                        submission_ids=submission_ids,
                        idempotency_key=f"stage11-partial-confirm-{uuid4()}",
                    ),
                )
                item_ids = tuple(item.id for item in creation.job.items)
                assert len(item_ids) >= 2
                attempt_id = (
                    await seed_successful_attempts(
                        connection,
                        owner_id,
                        creation.job.id,
                        item_ids[:1],
                        job_status="running",
                    )
                )[0]
                review_repository = SqlAlchemyReviewRepository(transactional_database)
                draft = await review_repository.save_draft(
                    owner_id,
                    item_ids[0],
                    review_data(attempt_id),
                )

                await review_repository.confirm_reviews(
                    owner_id,
                    creation.job.id,
                    (
                        ReviewConfirmationRef(
                            item_id=item_ids[0],
                            review_id=draft.id,
                            revision_number=draft.revision_number,
                        ),
                    ),
                )

                job_status = await connection.scalar(
                    text("select status from grading_jobs where id = :job_id"),
                    {"job_id": creation.job.id},
                )
                remaining_status = await connection.scalar(
                    text("select status from grading_job_items where id = :item_id"),
                    {"item_id": item_ids[1]},
                )
                dispatchable = await grading_repository.list_dispatchable_items()
                assert job_status == "running"
                assert remaining_status == "queued"
                assert item_ids[1] in {item_id for item_id, _ in dispatchable}
            finally:
                await outer_transaction.rollback()
    finally:
        await database.dispose()


def review_data(attempt_id: UUID) -> ReviewDraftData:
    return ReviewDraftData(
        attempt_id=attempt_id,
        criteria=(
            ReviewCriterionInput(
                dimension_id="content",
                score="8",
                reason="The response addresses the task.",
                revision_suggestions=("Add a fuller explanation.",),
            ),
        ),
        deductions=(),
        evidence=(
            ReviewEvidenceInput(
                target_type="dimension",
                target_id="content",
                block_id="b000001",
                quote="Exact evidence",
            ),
        ),
        overall_feedback="A clear response with room for fuller explanation.",
        change_reason=None,
        subtotal=8,
        deduction_total=0,
        final_score=8,
    )


@pytest.mark.postgres
def test_stage_eleven_teacher_permissions_and_atomic_batch_confirmation() -> None:
    asyncio.run(assert_stage_eleven_confirmation_contract())


async def assert_stage_eleven_confirmation_contract() -> None:
    settings = TestMigrationSettings()
    database = build_test_database(settings)
    owner_id = settings.test_teacher_auth_user_id
    other_owner_id = settings.test_other_auth_user_id
    try:
        async with database.engine.connect() as connection:
            baseline_counts = tuple(
                (
                    await connection.execute(
                        text(
                            "select "
                            "(select count(*) from public.grading_jobs), "
                            "(select count(*) from public.grading_job_items), "
                            "(select count(*) from public.grading_attempts), "
                            "(select count(*) from public.teacher_reviews)"
                        )
                    )
                ).one()
            )
            await connection.commit()
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
                await connection.execute(text("set local role none"))
                assert (
                    await connection.scalar(text("select version_num from alembic_version"))
                    == STAGE_ELEVEN_REVISION
                )
                assignment_id, submission_ids = await seed_teacher_batch_fixture(
                    connection,
                    owner_id,
                    expected_revision=STAGE_ELEVEN_REVISION,
                    require_empty_grading_tables=False,
                )
                other_auth_user_exists = await connection.scalar(
                    text("select exists(select 1 from auth.users where id = :other_owner_id)"),
                    {"other_owner_id": other_owner_id},
                )
                if not other_auth_user_exists:
                    pytest.fail(
                        "阶段十一权限回归缺少 TEST_OTHER_AUTH_USER_ID 对应的 Auth 用户。",
                        pytrace=False,
                    )
                other_profile = await connection.scalar(
                    text("select id from profiles where id = :other_owner_id"),
                    {"other_owner_id": other_owner_id},
                )
                if other_profile is None:
                    await connection.execute(
                        text(
                            "insert into profiles(id, role, status, display_name) "
                            "values (:id, 'teacher', 'active', "
                            "'Stage Eleven Other Teacher')"
                        ),
                        {"id": other_owner_id},
                    )
                else:
                    await connection.execute(
                        text(
                            "update profiles set role = 'teacher', status = 'active' where id = :id"
                        ),
                        {"id": other_owner_id},
                    )
                grading_repository = SqlAlchemyGradingJobRepository(transactional_database)
                creation = await grading_repository.create_or_get_job(
                    owner_id,
                    assignment_id,
                    GradingJobCreate(
                        submission_ids=submission_ids,
                        idempotency_key=f"stage11-confirm-{uuid4()}",
                    ),
                )
                item_ids = tuple(item.id for item in creation.job.items)
                review_repository = SqlAlchemyReviewRepository(transactional_database)
                owner_jobs = await review_repository.list_jobs(owner_id)
                assert creation.job.id in {job.id for job in owner_jobs}
                attempt_ids = await seed_successful_attempts(
                    connection,
                    owner_id,
                    creation.job.id,
                    item_ids,
                )
                original_attempts = list(
                    await connection.execute(
                        text(
                            "select id, criteria_results, total_score from grading_attempts "
                            "where id = any(:attempt_ids) order by id"
                        ),
                        {"attempt_ids": list(attempt_ids)},
                    )
                )
                saved_drafts = []
                for index, (item_id, attempt_id) in enumerate(
                    zip(item_ids, attempt_ids, strict=True)
                ):
                    first_draft = await review_repository.save_draft(
                        owner_id,
                        item_id,
                        review_data(attempt_id),
                    )
                    if index == 0:
                        revised_draft = await review_repository.save_draft(
                            owner_id,
                            item_id,
                            review_data(attempt_id),
                        )
                        assert revised_draft.id == first_draft.id
                        assert revised_draft.revision_number == first_draft.revision_number + 1
                        saved_drafts.append(revised_draft)
                    else:
                        saved_drafts.append(first_draft)
                drafts = tuple(saved_drafts)
                references = tuple(
                    ReviewConfirmationRef(
                        item_id=item_id,
                        review_id=draft.id,
                        revision_number=draft.revision_number,
                    )
                    for item_id, draft in zip(item_ids, drafts, strict=True)
                )
                bad_references = (
                    references[0],
                    references[1].model_copy(
                        update={"revision_number": references[1].revision_number + 1}
                    ),
                )
                with pytest.raises(ReviewNotFoundError):
                    await review_repository.confirm_reviews(
                        owner_id,
                        creation.job.id,
                        bad_references,
                    )
                assert set(
                    await connection.scalars(
                        text("select status from teacher_reviews where owner_id = :owner_id"),
                        {"owner_id": owner_id},
                    )
                ) == {"draft"}

                confirmed = await review_repository.confirm_reviews(
                    owner_id,
                    creation.job.id,
                    references,
                )
                repeated = await review_repository.confirm_reviews(
                    owner_id,
                    creation.job.id,
                    references,
                )
                assert [review.id for review in confirmed.reviews] == [
                    review.id for review in repeated.reviews
                ]
                assert confirmed.completed_job_ids == (creation.job.id,)
                job_state = (
                    await connection.execute(
                        text("select status, finished_at from grading_jobs where id = :job_id"),
                        {"job_id": creation.job.id},
                    )
                ).one()
                assert job_state.status == "completed"
                assert job_state.finished_at is not None
                assert set(
                    await connection.scalars(
                        text("select status from grading_job_items where grading_job_id = :job_id"),
                        {"job_id": creation.job.id},
                    )
                ) == {"completed"}
                assert (
                    await connection.scalar(
                        text(
                            "select count(*) from audit_logs "
                            "where action = 'teacher_review.confirmed' "
                            "and resource_id = any(:review_ids)"
                        ),
                        {"review_ids": [review.id for review in drafts]},
                    )
                    == 2
                )
                assert (
                    list(
                        await connection.execute(
                            text(
                                "select id, criteria_results, total_score from grading_attempts "
                                "where id = any(:attempt_ids) order by id"
                            ),
                            {"attempt_ids": list(attempt_ids)},
                        )
                    )
                    == original_attempts
                )

                other_owner_jobs = await review_repository.list_jobs(other_owner_id)
                assert creation.job.id not in {job.id for job in other_owner_jobs}

                await connection.execute(text("set local role none"))
                with pytest.raises(DBAPIError):
                    await connection.execute(
                        text(
                            "update teacher_reviews set feedback = 'overwritten' "
                            "where id = :review_id"
                        ),
                        {"review_id": drafts[0].id},
                    )
            finally:
                await outer_transaction.rollback()
                preserved_counts = tuple(
                    (
                        await connection.execute(
                            text(
                                "select "
                                "(select count(*) from public.grading_jobs), "
                                "(select count(*) from public.grading_job_items), "
                                "(select count(*) from public.grading_attempts), "
                                "(select count(*) from public.teacher_reviews)"
                            )
                        )
                    ).one()
                )
                assert preserved_counts == baseline_counts
    finally:
        await database.dispose()
