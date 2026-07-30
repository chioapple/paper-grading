"""阶段十三独立 Supabase 测试项目的配额与最小权限契约。"""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import TestMigrationSettings

STAGE_TWELVE_REVISION = "20260722_0017"
STAGE_THIRTEEN_REVISION = "20260726_0018"
STAGE_THIRTEEN_STORAGE_BUCKET = "paper-grading-test"
STAGE_THIRTEEN_STORAGE_CAPACITY_BYTES = 1_000_000_000
INTERNAL_TABLES = {
    "quota_resource_states",
    "quota_reservations",
    "quota_alerts",
    "retention_policies",
    "retention_objects",
    "backup_policies",
    "backup_runs",
    "backup_restore_runs",
}
FUNCTION_SIGNATURES = {
    "database_quota": "paper_grading_private.check_database_growth(text,bigint)",
    "storage_quota": ("paper_grading_private.reserve_storage_growth(text,text,bytea,bigint)"),
    "storage_finalize": "paper_grading_private.finalize_storage_growth(uuid,text)",
    "retention_list": "paper_grading_private.list_retention_candidates(integer)",
    "retention_claim": ("paper_grading_private.claim_next_retention_object(uuid,integer)"),
    "retention_revalidate": ("paper_grading_private.revalidate_retention_object(uuid,uuid)"),
    "retention_complete": ("paper_grading_private.complete_retention_object(uuid,uuid,text)"),
    "retention_fail": ("paper_grading_private.fail_retention_object(uuid,uuid,text)"),
}


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


async def replay_stage_thirteen(settings: TestMigrationSettings) -> None:
    engine = create_async_engine(settings.test_migration_database_url, poolclass=NullPool)
    config = build_alembic_config()
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("select version_num from alembic_version"))
            await connection.commit()
            assert revision in {STAGE_TWELVE_REVISION, STAGE_THIRTEEN_REVISION}
            if revision == STAGE_THIRTEEN_REVISION:
                await run_alembic_on_connection(
                    connection,
                    config,
                    command.downgrade,
                    STAGE_TWELVE_REVISION,
                )
            await run_alembic_on_connection(
                connection,
                config,
                command.upgrade,
                STAGE_THIRTEEN_REVISION,
            )
            await run_alembic_on_connection(
                connection,
                config,
                command.downgrade,
                STAGE_TWELVE_REVISION,
            )
            await run_alembic_on_connection(
                connection,
                config,
                command.upgrade,
                STAGE_THIRTEEN_REVISION,
            )
            final_revision = await connection.scalar(
                text("select version_num from alembic_version")
            )
            assert final_revision == STAGE_THIRTEEN_REVISION
    finally:
        await engine.dispose()


async def read_catalog(settings: TestMigrationSettings) -> dict[str, Any]:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            tables = {
                row.relname: row
                for row in await connection.execute(
                    text(
                        """
                        select class.relname, class.relrowsecurity, class.relforcerowsecurity
                        from pg_catalog.pg_class class
                        join pg_catalog.pg_namespace namespace
                          on namespace.oid = class.relnamespace
                        where namespace.nspname = 'public'
                          and class.relname = any(cast(:tables as text[]))
                        """
                    ),
                    {"tables": sorted(INTERNAL_TABLES)},
                )
            }
            roles = {
                row.rolname: row
                for row in await connection.execute(
                    text(
                        """
                        select rolname, rolcanlogin, rolinherit, rolbypassrls
                        from pg_catalog.pg_roles
                        where rolname in (
                          'paper_grading_retention_worker',
                          'paper_grading_backup_worker'
                        )
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
                            select procedure.prosecdef, procedure.proconfig,
                                   has_function_privilege(
                                     'anon', cast(:signature as regprocedure), 'execute'
                                   ) as anon_can_execute,
                                   has_function_privilege(
                                     'authenticated',
                                     cast(:signature as regprocedure), 'execute'
                                   ) as authenticated_can_execute,
                                   has_function_privilege(
                                     'service_role',
                                     cast(:signature as regprocedure), 'execute'
                                   ) as service_role_can_execute
                            from pg_catalog.pg_proc procedure
                            where procedure.oid = cast(:signature as regprocedure)
                            """
                        ),
                        {"signature": signature},
                    )
                ).one()
            return {"tables": tables, "roles": roles, "functions": functions}
    finally:
        await engine.dispose()


async def exercise_invalid_quota_requests(settings: TestMigrationSettings) -> None:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            database = (
                await connection.execute(
                    text(
                        """
                        select state, error_code
                        from paper_grading_private.check_database_growth('', 1)
                        """
                    )
                )
            ).one()
            storage = (
                await connection.execute(
                    text(
                        """
                        select state, error_code
                        from paper_grading_private.reserve_storage_growth(
                          '',
                          'stage13-acceptance/invalid.bin',
                          decode(repeat('13', 32), 'hex'),
                          1
                        )
                        """
                    )
                )
            ).one()
            await connection.rollback()

        assert tuple(database) == ("unavailable", "quota_request_invalid")
        assert tuple(storage) == ("unavailable", "quota_request_invalid")
    finally:
        await engine.dispose()


async def exercise_concurrent_storage_reservations(
    settings: TestMigrationSettings,
) -> None:
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    run_id = uuid4().hex
    operation_keys = (
        f"stage13-acceptance-concurrent-a-{run_id}",
        f"stage13-acceptance-concurrent-b-{run_id}",
    )
    object_keys = (
        f"stage13-acceptance/{run_id}/a.bin",
        f"stage13-acceptance/{run_id}/b.bin",
    )
    original_config: dict[str, object] | None = None
    original_alert_ids: set[object] = set()
    configured = False

    try:
        async with engine.begin() as connection:
            bucket_exists = await connection.scalar(
                text(
                    """
                    select exists(
                      select 1 from storage.buckets where id = :bucket_id
                    )
                    """
                ),
                {"bucket_id": STAGE_THIRTEEN_STORAGE_BUCKET},
            )
            assert bucket_exists, "阶段 13 测试 Storage bucket 不存在"

            config = (
                (
                    await connection.execute(
                        text(
                            """
                        select enabled, capacity_bytes, warning_ratio, hard_limit_ratio,
                               source_identifier, last_used_bytes, last_checked_at,
                               last_error_code, updated_at
                        from public.quota_resource_states
                        where resource = 'storage'
                        for update
                        """
                        )
                    )
                )
                .mappings()
                .one()
            )
            original_config = dict(config)
            assert config["enabled"] is False, "真实并发验收前 Storage 配额必须保持关闭"

            reservation_count = await connection.scalar(
                text("select count(*) from public.quota_reservations")
            )
            assert reservation_count == 0, "真实并发验收前必须先审查已有配额预留"

            original_alert_ids = set(
                (await connection.execute(text("select id from public.quota_alerts"))).scalars()
            )
            storage_used = await connection.scalar(
                text(
                    """
                    select coalesce(sum((metadata->>'size')::bigint)::bigint, 0::bigint)
                    from storage.objects
                    where bucket_id = :bucket_id
                    """
                ),
                {"bucket_id": STAGE_THIRTEEN_STORAGE_BUCKET},
            )
            assert isinstance(storage_used, int)
            hard_limit_bytes = 850_000_000
            assert storage_used < hard_limit_bytes - 2, (
                "测试桶已接近 Storage 硬限制，不能安全执行并发验收"
            )
            requested_bytes = (hard_limit_bytes - storage_used + 1) // 2
            assert storage_used + requested_bytes < hard_limit_bytes
            assert storage_used + 2 * requested_bytes >= hard_limit_bytes

            await connection.execute(
                text(
                    """
                    update public.quota_resource_states
                    set enabled = true,
                        capacity_bytes = :capacity_bytes,
                        warning_ratio = 0.7000,
                        hard_limit_ratio = 0.8500,
                        source_identifier = :bucket_id
                    where resource = 'storage'
                    """
                ),
                {
                    "capacity_bytes": STAGE_THIRTEEN_STORAGE_CAPACITY_BYTES,
                    "bucket_id": STAGE_THIRTEEN_STORAGE_BUCKET,
                },
            )
            configured = True

        start = asyncio.Event()

        async def reserve(index: int) -> dict[str, object]:
            await start.wait()
            async with engine.begin() as connection:
                row = (
                    (
                        await connection.execute(
                            text(
                                """
                            select *
                            from paper_grading_private.reserve_storage_growth(
                              :operation_key,
                              :object_key,
                              :content_sha256,
                              :requested_bytes
                            )
                            """
                            ),
                            {
                                "operation_key": operation_keys[index],
                                "object_key": object_keys[index],
                                "content_sha256": bytes.fromhex(f"{index + 1:02x}" * 32),
                                "requested_bytes": requested_bytes,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                return dict(row)

        async with asyncio.TaskGroup() as task_group:
            reservations = [task_group.create_task(reserve(index)) for index in range(2)]
            start.set()
        results = [reservation.result() for reservation in reservations]

        accepted = [result for result in results if result["state"] in {"ok", "warning"}]
        blocked = [result for result in results if result["state"] == "blocked"]
        assert len(accepted) == 1
        assert accepted[0]["reservation_id"] is not None
        assert len(blocked) == 1
        assert blocked[0]["reservation_id"] is None
    finally:
        if configured and original_config is not None:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        delete from public.quota_reservations
                        where operation_key in (:operation_key_a, :operation_key_b)
                        """
                    ),
                    {
                        "operation_key_a": operation_keys[0],
                        "operation_key_b": operation_keys[1],
                    },
                )
                current_alert_ids = set(
                    (await connection.execute(text("select id from public.quota_alerts"))).scalars()
                )
                for alert_id in current_alert_ids - original_alert_ids:
                    await connection.execute(
                        text("delete from public.quota_alerts where id = :alert_id"),
                        {"alert_id": alert_id},
                    )
                await connection.execute(
                    text(
                        """
                        update public.quota_resource_states
                        set enabled = :enabled,
                            capacity_bytes = :capacity_bytes,
                            warning_ratio = :warning_ratio,
                            hard_limit_ratio = :hard_limit_ratio,
                            source_identifier = :source_identifier,
                            last_used_bytes = :last_used_bytes,
                            last_checked_at = :last_checked_at,
                            last_error_code = :last_error_code,
                            updated_at = :updated_at
                        where resource = 'storage'
                        """
                    ),
                    original_config,
                )

            async with engine.connect() as connection:
                restored = (
                    (
                        await connection.execute(
                            text(
                                """
                            select enabled, capacity_bytes, warning_ratio, hard_limit_ratio,
                                   source_identifier, last_used_bytes, last_checked_at,
                                   last_error_code, updated_at
                            from public.quota_resource_states
                            where resource = 'storage'
                            """
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                remaining = await connection.scalar(
                    text(
                        """
                        select count(*) from public.quota_reservations
                        where operation_key in (:operation_key_a, :operation_key_b)
                        """
                    ),
                    {
                        "operation_key_a": operation_keys[0],
                        "operation_key_b": operation_keys[1],
                    },
                )
                await connection.rollback()
            assert dict(restored) == original_config
            assert remaining == 0
        await engine.dispose()


@pytest.mark.postgres
def test_stage_thirteen_migration_replays_on_the_isolated_project() -> None:
    asyncio.run(replay_stage_thirteen(TestMigrationSettings()))


@pytest.mark.postgres
def test_stage_thirteen_internal_catalog_is_not_exposed_to_data_api_roles() -> None:
    catalog = asyncio.run(read_catalog(TestMigrationSettings()))

    assert set(catalog["tables"]) == INTERNAL_TABLES
    assert all(row.relrowsecurity and row.relforcerowsecurity for row in catalog["tables"].values())
    assert set(catalog["roles"]) == {
        "paper_grading_retention_worker",
        "paper_grading_backup_worker",
    }
    assert all(
        role.rolcanlogin and not role.rolinherit and not role.rolbypassrls
        for role in catalog["roles"].values()
    )
    for function in catalog["functions"].values():
        assert function.prosecdef
        assert 'search_path=""' in function.proconfig
        assert not function.anon_can_execute
        assert not function.authenticated_can_execute
        assert not function.service_role_can_execute


@pytest.mark.postgres
def test_stage_thirteen_invalid_quota_requests_fail_closed() -> None:
    asyncio.run(exercise_invalid_quota_requests(TestMigrationSettings()))


@pytest.mark.postgres
def test_stage_thirteen_concurrent_storage_growth_cannot_cross_the_hard_limit() -> None:
    asyncio.run(exercise_concurrent_storage_reservations(TestMigrationSettings()))
