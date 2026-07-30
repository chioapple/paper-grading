"""建立阶段十三配额、保留和备份审计基础设施。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0018"
down_revision: str | None = "20260722_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETENTION_WORKER_ROLE = "paper_grading_retention_worker"
BACKUP_WORKER_ROLE = "paper_grading_backup_worker"
API_ROLES = ("PUBLIC", "anon", "authenticated", "service_role")


def _revoke_execute(signature: str) -> None:
    for role in API_ROLES:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {role}")


def _create_roles() -> None:
    for role in (RETENTION_WORKER_ROLE, BACKUP_WORKER_ROLE):
        op.execute(
            f"""
            DO $paper_grading$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}'
                ) THEN
                    CREATE ROLE {role} LOGIN NOINHERIT NOBYPASSRLS;
                END IF;
            END;
            $paper_grading$
            """
        )
        op.execute(f"ALTER ROLE {role} LOGIN NOINHERIT NOBYPASSRLS")
        op.execute(f"GRANT {role} TO postgres")
        op.execute(f"GRANT USAGE ON SCHEMA public, paper_grading_private TO {role}")


def _create_tables() -> None:
    op.create_table(
        "quota_resource_states",
        sa.Column("resource", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capacity_bytes", sa.BigInteger()),
        sa.Column(
            "warning_ratio",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0.7000"),
        ),
        sa.Column(
            "hard_limit_ratio",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0.8500"),
        ),
        sa.Column(
            "alert_dedupe_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3600"),
        ),
        sa.Column(
            "reservation_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("900"),
        ),
        sa.Column("source_identifier", sa.Text()),
        sa.Column("last_used_bytes", sa.BigInteger()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "resource in ('database', 'storage')",
            name="resource",
        ),
        sa.CheckConstraint(
            "capacity_bytes is null or capacity_bytes > 0",
            name="capacity",
        ),
        sa.CheckConstraint(
            "warning_ratio > 0 and warning_ratio < hard_limit_ratio and hard_limit_ratio <= 1",
            name="thresholds",
        ),
        sa.CheckConstraint(
            "alert_dedupe_seconds between 60 and 604800 "
            "and reservation_seconds between 60 and 3600",
            name="intervals",
        ),
        sa.CheckConstraint(
            "not enabled or (capacity_bytes is not null and "
            "(resource <> 'storage' or "
            "(source_identifier is not null and btrim(source_identifier) <> '')))",
            name="enabled_configuration",
        ),
        sa.CheckConstraint(
            "last_used_bytes is null or last_used_bytes >= 0",
            name="last_used",
        ),
    )
    op.execute(
        """
        INSERT INTO public.quota_resource_states(resource, enabled)
        VALUES ('database', false), ('storage', false)
        """
    )
    op.create_table(
        "quota_reservations",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("operation_key", sa.Text(), nullable=False, unique=True),
        sa.Column("object_key", sa.Text()),
        sa.Column("content_sha256", sa.LargeBinary(32)),
        sa.Column("requested_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("reserved_bytes_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("capacity_bytes_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("resource = 'storage'", name="resource"),
        sa.CheckConstraint(
            "status in ('reserved', 'committed', 'released', 'uncertain')",
            name="status",
        ),
        sa.CheckConstraint(
            "requested_bytes >= 0 and used_bytes_snapshot >= 0 "
            "and reserved_bytes_snapshot >= 0 and capacity_bytes_snapshot > 0",
            name="bytes",
        ),
        sa.CheckConstraint(
            "char_length(operation_key) between 1 and 200 "
            "and object_key is not null and btrim(object_key) <> '' "
            "and octet_length(content_sha256) = 32",
            name="identity",
        ),
    )
    op.create_index(
        "quota_reservations_active_idx",
        "quota_reservations",
        ["lease_expires_at", "object_key"],
        postgresql_where=sa.text("status = 'reserved'"),
    )
    op.create_table(
        "quota_alerts",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger()),
        sa.Column("reserved_bytes", sa.BigInteger()),
        sa.Column("requested_bytes", sa.BigInteger()),
        sa.Column("capacity_bytes", sa.BigInteger()),
        sa.Column("error_code", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("resource in ('database', 'storage')", name="resource"),
        sa.CheckConstraint(
            "state in ('warning', 'blocked', 'unavailable')",
            name="state",
        ),
        sa.CheckConstraint(
            "(state = 'unavailable' and error_code is not null) or "
            "(state <> 'unavailable' and used_bytes is not null "
            "and reserved_bytes is not null and requested_bytes is not null "
            "and capacity_bytes is not null)",
            name="payload",
        ),
    )
    op.create_index(
        "quota_alerts_resource_state_created_idx",
        "quota_alerts",
        ["resource", "state", "created_at"],
    )
    op.create_table(
        "retention_policies",
        sa.Column("category", sa.Text(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "category in ('submission_source', 'submission_extracted', 'grading_raw_response')",
            name="category",
        ),
        sa.CheckConstraint("retention_days between 1 and 3650", name="days"),
    )
    op.execute(
        """
        INSERT INTO public.retention_policies(category, enabled, retention_days)
        VALUES
            ('submission_source', false, 30),
            ('submission_extracted', false, 30),
            ('grading_raw_response', false, 30)
        """
    )
    op.create_table(
        "retention_objects",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False, unique=True),
        sa.Column("retention_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'candidate'")),
        sa.Column("hold_until", sa.DateTime(timezone=True)),
        sa.Column("hold_reason", sa.Text()),
        sa.Column("claim_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "claim_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.Text()),
        sa.Column("storage_result", sa.Text()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("category", "source_record_id"),
        sa.CheckConstraint(
            "category in ('submission_source', 'submission_extracted', 'grading_raw_response')",
            name="category",
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'running', 'completed', 'failed', 'invalidated')",
            name="status",
        ),
        sa.CheckConstraint(
            "(hold_until is null) = (hold_reason is null)",
            name="hold",
        ),
        sa.CheckConstraint(
            "(status = 'running' and claim_token is not null and lease_expires_at is not null "
            "and deleted_at is null and completed_at is null and storage_result is null) or "
            "(status in ('candidate', 'failed', 'invalidated') and claim_token is null "
            "and lease_expires_at is null and deleted_at is null and completed_at is null "
            "and storage_result is null) or "
            "(status = 'completed' and claim_token is null and lease_expires_at is null "
            "and deleted_at is not null and completed_at is not null "
            "and storage_result in ('deleted', 'missing'))",
            name="state",
        ),
        sa.CheckConstraint(
            "claim_count >= 0 and btrim(object_key) <> '' "
            "and eligible_at >= retention_anchor_at "
            "and (storage_result is null or storage_result in ('deleted', 'missing'))",
            name="payload",
        ),
    )
    op.create_index(
        "retention_objects_candidates_idx",
        "retention_objects",
        ["next_attempt_at", "eligible_at", "id"],
        postgresql_where=sa.text("status in ('candidate', 'failed')"),
    )
    op.create_index(
        "retention_objects_running_idx",
        "retention_objects",
        ["lease_expires_at", "id"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "retention_objects_owner_category_idx",
        "retention_objects",
        ["owner_id", "category"],
    )
    op.create_table(
        "backup_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("creation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cleanup_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "interval_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("24"),
        ),
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("7"),
        ),
        sa.Column("target_identifier", sa.Text()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="singleton"),
        sa.CheckConstraint(
            "interval_hours between 1 and 168 and retention_days between 1 and 3650",
            name="intervals",
        ),
        sa.CheckConstraint(
            "not creation_enabled or "
            "(target_identifier is not null and btrim(target_identifier) <> '')",
            name="target",
        ),
    )
    op.execute(
        """
        INSERT INTO public.backup_policies(
            id, creation_enabled, cleanup_enabled, interval_hours, retention_days
        )
        VALUES (1, false, false, 24, 7)
        """
    )
    op.create_table(
        "backup_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("scope_version", sa.Text(), nullable=False),
        sa.Column("migration_revision", sa.Text()),
        sa.Column("dump_tool_version", sa.Text()),
        sa.Column("encryption_version", sa.Text()),
        sa.Column("encryption_key_id", sa.Text()),
        sa.Column("manifest", postgresql.JSONB(none_as_null=True)),
        sa.Column("object_key", sa.Text(), unique=True),
        sa.Column("plaintext_size_bytes", sa.BigInteger()),
        sa.Column("plaintext_sha256", sa.LargeBinary(32)),
        sa.Column("ciphertext_size_bytes", sa.BigInteger()),
        sa.Column("ciphertext_sha256", sa.LargeBinary(32)),
        sa.Column("target_version", sa.Text()),
        sa.Column("claim_token", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'completed', 'failed')",
            name="status",
        ),
        sa.CheckConstraint(
            "btrim(scope_version) <> '' and "
            "(manifest is null or jsonb_typeof(manifest) = 'object')",
            name="manifest",
        ),
        sa.CheckConstraint(
            "(status = 'queued' and claim_token is null and started_at is null "
            "and finished_at is null and error_code is null) or "
            "(status = 'running' and claim_token is not null and lease_expires_at is not null "
            "and started_at is not null and finished_at is null) or "
            "(status = 'completed' and claim_token is null and lease_expires_at is null "
            "and finished_at is not null and object_key is not null "
            "and plaintext_size_bytes >= 0 and octet_length(plaintext_sha256) = 32 "
            "and ciphertext_size_bytes > 0 and octet_length(ciphertext_sha256) = 32 "
            "and target_version is not null and manifest is not null) or "
            "(status = 'failed' and claim_token is null and lease_expires_at is null "
            "and finished_at is not null and error_code is not null)",
            name="state",
        ),
    )
    op.create_index(
        "backup_runs_dispatch_idx",
        "backup_runs",
        ["status", "created_at"],
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_table(
        "backup_restore_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "backup_run_id",
            sa.Uuid(),
            sa.ForeignKey("backup_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("environment_fingerprint", sa.LargeBinary(32), nullable=False),
        sa.Column("restored_migration_revision", sa.Text()),
        sa.Column("checks", postgresql.JSONB(none_as_null=True)),
        sa.Column("error_code", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'completed', 'failed')",
            name="status",
        ),
        sa.CheckConstraint(
            "octet_length(environment_fingerprint) = 32 "
            "and (checks is null or jsonb_typeof(checks) = 'object')",
            name="payload",
        ),
        sa.CheckConstraint(
            "(status = 'queued' and started_at is null and finished_at is null) or "
            "(status = 'running' and started_at is not null and finished_at is null) or "
            "(status = 'completed' and started_at is not null and finished_at is not null "
            "and restored_migration_revision is not null and checks is not null) or "
            "(status = 'failed' and started_at is not null and finished_at is not null "
            "and error_code is not null)",
            name="state",
        ),
    )
    op.create_index(
        "backup_restore_runs_backup_created_idx",
        "backup_restore_runs",
        ["backup_run_id", "created_at"],
    )


def _create_quota_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.check_database_growth(
            p_operation_key text,
            p_requested_bytes bigint
        )
        RETURNS TABLE(
            state text,
            resource text,
            reservation_id uuid,
            used_bytes bigint,
            reserved_bytes bigint,
            requested_bytes bigint,
            capacity_bytes bigint,
            error_code text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            config public.quota_resource_states%ROWTYPE;
            current_used bigint;
            current_state text;
        BEGIN
            IF p_operation_key IS NULL OR btrim(p_operation_key) = ''
               OR char_length(p_operation_key) > 200 OR p_requested_bytes < 0 THEN
                RETURN QUERY SELECT 'unavailable', 'database', NULL::uuid, 0::bigint,
                    0::bigint, GREATEST(p_requested_bytes, 0),
                    NULL::bigint, 'quota_request_invalid';
                RETURN;
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('paper_grading:quota:database', 0)
            );
            SELECT * INTO config
            FROM public.quota_resource_states q
            WHERE q.resource = 'database'
            FOR UPDATE;
            IF NOT config.enabled THEN
                RETURN QUERY SELECT 'ok', 'database', NULL::uuid, 0::bigint, 0::bigint,
                    p_requested_bytes, NULL::bigint, NULL::text;
                RETURN;
            END IF;
            BEGIN
                current_used := pg_catalog.pg_database_size(pg_catalog.current_database());
                IF current_used IS NULL THEN
                    RAISE EXCEPTION 'database usage unavailable';
                END IF;
            EXCEPTION WHEN OTHERS THEN
                UPDATE public.quota_resource_states
                SET last_checked_at = pg_catalog.transaction_timestamp(),
                    last_error_code = 'database_usage_unavailable',
                    updated_at = pg_catalog.transaction_timestamp()
                WHERE quota_resource_states.resource = 'database';
                INSERT INTO public.quota_alerts(resource, state, error_code)
                SELECT 'database', 'unavailable', 'database_usage_unavailable'
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.quota_alerts a
                    WHERE a.resource = 'database' AND a.state = 'unavailable'
                      AND a.created_at >= pg_catalog.transaction_timestamp()
                          - pg_catalog.make_interval(secs => config.alert_dedupe_seconds)
                );
                RETURN QUERY SELECT 'unavailable', 'database', NULL::uuid, 0::bigint,
                    0::bigint, p_requested_bytes, config.capacity_bytes,
                    'database_usage_unavailable';
                RETURN;
            END;
            current_state := CASE
                WHEN current_used + p_requested_bytes
                    >= pg_catalog.ceil(config.capacity_bytes * config.hard_limit_ratio)
                    THEN 'blocked'
                WHEN current_used + p_requested_bytes
                    >= pg_catalog.ceil(config.capacity_bytes * config.warning_ratio)
                    THEN 'warning'
                ELSE 'ok'
            END;
            UPDATE public.quota_resource_states
            SET last_used_bytes = current_used,
                last_checked_at = pg_catalog.transaction_timestamp(),
                last_error_code = NULL,
                updated_at = pg_catalog.transaction_timestamp()
            WHERE quota_resource_states.resource = 'database';
            IF current_state IN ('warning', 'blocked') THEN
                INSERT INTO public.quota_alerts(
                    resource, state, used_bytes, reserved_bytes,
                    requested_bytes, capacity_bytes
                )
                SELECT 'database', current_state, current_used, 0,
                    p_requested_bytes, config.capacity_bytes
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.quota_alerts a
                    WHERE a.resource = 'database' AND a.state = current_state
                      AND a.created_at >= pg_catalog.transaction_timestamp()
                          - pg_catalog.make_interval(secs => config.alert_dedupe_seconds)
                );
            END IF;
            RETURN QUERY SELECT current_state, 'database', NULL::uuid, current_used,
                0::bigint, p_requested_bytes, config.capacity_bytes, NULL::text;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.reserve_storage_growth(
            p_operation_key text,
            p_object_key text,
            p_content_sha256 bytea,
            p_requested_bytes bigint
        )
        RETURNS TABLE(
            state text,
            resource text,
            reservation_id uuid,
            used_bytes bigint,
            reserved_bytes bigint,
            requested_bytes bigint,
            capacity_bytes bigint,
            error_code text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            config public.quota_resource_states%ROWTYPE;
            existing public.quota_reservations%ROWTYPE;
            current_used bigint;
            current_reserved bigint;
            replaced_size bigint;
            projected bigint;
            current_state text;
            created_id uuid;
        BEGIN
            IF p_operation_key IS NULL OR btrim(p_operation_key) = ''
               OR char_length(p_operation_key) > 200
               OR p_object_key IS NULL OR btrim(p_object_key) = ''
               OR pg_catalog.octet_length(p_content_sha256) <> 32
               OR p_requested_bytes < 0 THEN
                RETURN QUERY SELECT 'unavailable', 'storage', NULL::uuid, 0::bigint,
                    0::bigint, GREATEST(p_requested_bytes, 0),
                    NULL::bigint, 'quota_request_invalid';
                RETURN;
            END IF;
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended('paper_grading:quota:storage', 0)
            );
            SELECT * INTO config
            FROM public.quota_resource_states q
            WHERE q.resource = 'storage'
            FOR UPDATE;
            IF NOT config.enabled THEN
                RETURN QUERY SELECT 'ok', 'storage', NULL::uuid, 0::bigint, 0::bigint,
                    p_requested_bytes, NULL::bigint, NULL::text;
                RETURN;
            END IF;
            SELECT * INTO existing
            FROM public.quota_reservations r
            WHERE r.operation_key = p_operation_key;
            IF FOUND THEN
                IF existing.object_key IS DISTINCT FROM p_object_key
                   OR existing.content_sha256 IS DISTINCT FROM p_content_sha256
                   OR existing.requested_bytes IS DISTINCT FROM p_requested_bytes THEN
                    RETURN QUERY SELECT 'unavailable', 'storage', existing.id,
                        existing.used_bytes_snapshot, existing.reserved_bytes_snapshot,
                        p_requested_bytes, existing.capacity_bytes_snapshot,
                        'quota_idempotency_conflict';
                    RETURN;
                END IF;
                IF existing.status = 'reserved'
                   AND existing.lease_expires_at > pg_catalog.transaction_timestamp() THEN
                    RETURN QUERY SELECT 'ok', 'storage', existing.id,
                        existing.used_bytes_snapshot, existing.reserved_bytes_snapshot,
                        existing.requested_bytes, existing.capacity_bytes_snapshot, NULL::text;
                    RETURN;
                ELSIF existing.status = 'committed' THEN
                    RETURN QUERY SELECT 'ok', 'storage', existing.id,
                        existing.used_bytes_snapshot, existing.reserved_bytes_snapshot,
                        existing.requested_bytes, existing.capacity_bytes_snapshot, NULL::text;
                    RETURN;
                ELSIF existing.status = 'reserved' THEN
                    UPDATE public.quota_reservations
                    SET status = 'uncertain', updated_at = pg_catalog.transaction_timestamp()
                    WHERE id = existing.id;
                    existing.status := 'uncertain';
                END IF;
            END IF;
            BEGIN
                SELECT
                    COALESCE(
                        pg_catalog.sum((o.metadata->>'size')::bigint),
                        0
                    ),
                    COALESCE(
                        pg_catalog.max(
                            CASE WHEN o.name = p_object_key
                                THEN (o.metadata->>'size')::bigint ELSE 0 END
                        ),
                        0
                    )
                INTO current_used, replaced_size
                FROM storage.objects o
                WHERE o.bucket_id = config.source_identifier;
            EXCEPTION WHEN OTHERS THEN
                UPDATE public.quota_resource_states
                SET last_checked_at = pg_catalog.transaction_timestamp(),
                    last_error_code = 'storage_usage_unavailable',
                    updated_at = pg_catalog.transaction_timestamp()
                WHERE quota_resource_states.resource = 'storage';
                INSERT INTO public.quota_alerts(resource, state, error_code)
                SELECT 'storage', 'unavailable', 'storage_usage_unavailable'
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.quota_alerts a
                    WHERE a.resource = 'storage' AND a.state = 'unavailable'
                      AND a.created_at >= pg_catalog.transaction_timestamp()
                          - pg_catalog.make_interval(secs => config.alert_dedupe_seconds)
                );
                RETURN QUERY SELECT 'unavailable', 'storage', NULL::uuid, 0::bigint,
                    0::bigint, p_requested_bytes, config.capacity_bytes,
                    'storage_usage_unavailable';
                RETURN;
            END;
            UPDATE public.quota_reservations
            SET status = 'uncertain', updated_at = pg_catalog.transaction_timestamp()
            WHERE status = 'reserved'
              AND lease_expires_at <= pg_catalog.transaction_timestamp();
            SELECT COALESCE(pg_catalog.sum(r.requested_bytes), 0)
            INTO current_reserved
            FROM public.quota_reservations r
            WHERE (
                (r.status = 'reserved'
                 AND r.lease_expires_at > pg_catalog.transaction_timestamp())
                OR (
                    r.status IN ('committed', 'uncertain')
                    AND NOT EXISTS (
                        SELECT 1
                        FROM storage.objects counted
                        WHERE counted.bucket_id = config.source_identifier
                          AND counted.name = r.object_key
                    )
                )
              )
              AND r.object_key <> p_object_key;
            projected := current_used - replaced_size + current_reserved + p_requested_bytes;
            current_state := CASE
                WHEN projected >= pg_catalog.ceil(
                    config.capacity_bytes * config.hard_limit_ratio
                ) THEN 'blocked'
                WHEN projected >= pg_catalog.ceil(
                    config.capacity_bytes * config.warning_ratio
                ) THEN 'warning'
                ELSE 'ok'
            END;
            UPDATE public.quota_resource_states
            SET last_used_bytes = current_used,
                last_checked_at = pg_catalog.transaction_timestamp(),
                last_error_code = NULL,
                updated_at = pg_catalog.transaction_timestamp()
            WHERE quota_resource_states.resource = 'storage';
            IF current_state IN ('warning', 'blocked') THEN
                INSERT INTO public.quota_alerts(
                    resource, state, used_bytes, reserved_bytes,
                    requested_bytes, capacity_bytes
                )
                SELECT 'storage', current_state, current_used, current_reserved,
                    p_requested_bytes, config.capacity_bytes
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.quota_alerts a
                    WHERE a.resource = 'storage' AND a.state = current_state
                      AND a.created_at >= pg_catalog.transaction_timestamp()
                          - pg_catalog.make_interval(secs => config.alert_dedupe_seconds)
                );
            END IF;
            IF current_state = 'blocked' THEN
                RETURN QUERY SELECT current_state, 'storage', NULL::uuid, current_used,
                    current_reserved, p_requested_bytes, config.capacity_bytes, NULL::text;
                RETURN;
            END IF;
            IF existing.id IS NOT NULL THEN
                UPDATE public.quota_reservations
                SET status = 'reserved',
                    used_bytes_snapshot = current_used - replaced_size,
                    reserved_bytes_snapshot = current_reserved,
                    capacity_bytes_snapshot = config.capacity_bytes,
                    lease_expires_at = pg_catalog.transaction_timestamp()
                        + pg_catalog.make_interval(secs => config.reservation_seconds),
                    updated_at = pg_catalog.transaction_timestamp()
                WHERE id = existing.id
                RETURNING id INTO created_id;
            ELSE
                INSERT INTO public.quota_reservations(
                    resource, operation_key, object_key, content_sha256, requested_bytes,
                    used_bytes_snapshot, reserved_bytes_snapshot, capacity_bytes_snapshot,
                    status, lease_expires_at
                )
                VALUES (
                    'storage', p_operation_key, p_object_key, p_content_sha256,
                    p_requested_bytes, current_used - replaced_size, current_reserved,
                    config.capacity_bytes, 'reserved', pg_catalog.transaction_timestamp()
                        + pg_catalog.make_interval(secs => config.reservation_seconds)
                )
                RETURNING id INTO created_id;
            END IF;
            RETURN QUERY SELECT current_state, 'storage', created_id,
                current_used - replaced_size,
                current_reserved, p_requested_bytes, config.capacity_bytes, NULL::text;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.finalize_storage_growth(
            p_reservation_id uuid,
            p_status text
        )
        RETURNS TABLE(
            state text,
            resource text,
            reservation_id uuid,
            used_bytes bigint,
            reserved_bytes bigint,
            requested_bytes bigint,
            capacity_bytes bigint,
            error_code text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            current_reservation public.quota_reservations%ROWTYPE;
        BEGIN
            IF p_status NOT IN ('committed', 'released', 'uncertain') THEN
                RETURN QUERY SELECT 'unavailable', 'storage', p_reservation_id,
                    0::bigint, 0::bigint, 0::bigint, NULL::bigint,
                    'quota_finalize_invalid';
                RETURN;
            END IF;
            SELECT * INTO current_reservation
            FROM public.quota_reservations r
            WHERE r.id = p_reservation_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN QUERY SELECT 'unavailable', 'storage', p_reservation_id,
                    0::bigint, 0::bigint, 0::bigint, NULL::bigint,
                    'quota_reservation_not_found';
                RETURN;
            END IF;
            IF current_reservation.status IN ('reserved', 'uncertain') THEN
                UPDATE public.quota_reservations
                SET status = p_status, updated_at = pg_catalog.transaction_timestamp()
                WHERE id = p_reservation_id;
                current_reservation.status := p_status;
            ELSIF current_reservation.status <> p_status THEN
                RETURN QUERY SELECT 'unavailable', 'storage', current_reservation.id,
                    current_reservation.used_bytes_snapshot,
                    current_reservation.reserved_bytes_snapshot,
                    current_reservation.requested_bytes,
                    current_reservation.capacity_bytes_snapshot,
                    'quota_finalize_conflict';
                RETURN;
            END IF;
            RETURN QUERY SELECT 'ok', 'storage', current_reservation.id,
                current_reservation.used_bytes_snapshot,
                current_reservation.reserved_bytes_snapshot,
                current_reservation.requested_bytes,
                current_reservation.capacity_bytes_snapshot, NULL::text;
        END;
        $$
        """
    )
    for signature in (
        "paper_grading_private.check_database_growth(text, bigint)",
        "paper_grading_private.reserve_storage_growth(text, text, bytea, bigint)",
        "paper_grading_private.finalize_storage_growth(uuid, text)",
    ):
        _revoke_execute(signature)
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.check_database_growth(text, bigint) "
        "TO paper_grading_teacher_api"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.reserve_storage_growth(text, text, bytea, bigint) "
        "TO paper_grading_retention_worker, paper_grading_export_worker"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.finalize_storage_growth(uuid, text) "
        "TO paper_grading_retention_worker, paper_grading_export_worker"
    )


def _create_retention_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.list_retention_candidates(
            p_limit integer
        )
        RETURNS TABLE(
            id uuid,
            object_class text,
            object_key text,
            eligible_at timestamptz
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = ''
        STABLE
        AS $$
            SELECT r.id, r.category, r.object_key, r.eligible_at
            FROM public.retention_objects r
            WHERE p_limit BETWEEN 1 AND 1000
              AND r.status IN ('candidate', 'failed')
              AND r.eligible_at <= pg_catalog.transaction_timestamp()
              AND (r.next_attempt_at IS NULL
                   OR r.next_attempt_at <= pg_catalog.transaction_timestamp())
              AND (r.hold_until IS NULL
                   OR r.hold_until <= pg_catalog.transaction_timestamp())
            ORDER BY r.eligible_at, r.id
            LIMIT COALESCE(
                GREATEST(0, LEAST(p_limit, 1000)),
                0
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.claim_next_retention_object(
            p_claim_token uuid,
            p_lease_seconds integer
        )
        RETURNS TABLE(
            id uuid,
            object_class text,
            object_key text,
            eligible_at timestamptz,
            lease_token uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            selected_id uuid;
        BEGIN
            IF p_claim_token IS NULL OR p_lease_seconds NOT BETWEEN 30 AND 900 THEN
                RETURN;
            END IF;
            SELECT r.id INTO selected_id
            FROM public.retention_objects r
            JOIN public.retention_policies p ON p.category = r.category
            WHERE p.enabled = true
              AND r.eligible_at <= pg_catalog.transaction_timestamp()
              AND (r.next_attempt_at IS NULL
                   OR r.next_attempt_at <= pg_catalog.transaction_timestamp())
              AND (r.hold_until IS NULL
                   OR r.hold_until <= pg_catalog.transaction_timestamp())
              AND (
                  r.status IN ('candidate', 'failed')
                  OR (
                      r.status = 'running'
                      AND r.lease_expires_at <= pg_catalog.transaction_timestamp()
                  )
              )
            ORDER BY r.eligible_at, r.id
            FOR UPDATE OF r SKIP LOCKED
            LIMIT 1;
            IF selected_id IS NULL THEN
                RETURN;
            END IF;
            RETURN QUERY
            UPDATE public.retention_objects r
            SET status = 'running',
                claim_token = p_claim_token,
                lease_expires_at = pg_catalog.transaction_timestamp()
                    + pg_catalog.make_interval(secs => p_lease_seconds),
                claim_count = r.claim_count + 1,
                next_attempt_at = NULL,
                last_error_code = NULL,
                updated_at = pg_catalog.transaction_timestamp()
            WHERE r.id = selected_id
            RETURNING r.id, r.category, r.object_key, r.eligible_at, r.claim_token;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.revalidate_retention_object(
            p_object_id uuid,
            p_claim_token uuid
        )
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            current_object public.retention_objects%ROWTYPE;
            policy_enabled boolean;
        BEGIN
            SELECT * INTO current_object
            FROM public.retention_objects r
            WHERE r.id = p_object_id
            FOR UPDATE;
            IF NOT FOUND
               OR current_object.status <> 'running'
               OR current_object.claim_token IS DISTINCT FROM p_claim_token
               OR current_object.lease_expires_at <= pg_catalog.transaction_timestamp() THEN
                RETURN 'lease_lost';
            END IF;
            SELECT p.enabled INTO policy_enabled
            FROM public.retention_policies p
            WHERE p.category = current_object.category;
            IF policy_enabled IS DISTINCT FROM true
               OR current_object.eligible_at > pg_catalog.transaction_timestamp()
               OR (
                   current_object.hold_until IS NOT NULL
                   AND current_object.hold_until > pg_catalog.transaction_timestamp()
               )
               OR (
                   current_object.category = 'submission_source'
                   AND NOT EXISTS (
                       SELECT 1
                       FROM public.submissions s
                       WHERE s.id = current_object.source_record_id
                         AND s.owner_id = current_object.owner_id
                         AND s.source_object_key = current_object.object_key
                   )
               )
               OR (
                   current_object.category = 'submission_extracted'
                   AND NOT EXISTS (
                       SELECT 1
                       FROM public.submissions s
                       WHERE s.id = current_object.source_record_id
                         AND s.owner_id = current_object.owner_id
                         AND s.extracted_object_key = current_object.object_key
                   )
               )
               OR (
                   current_object.category = 'grading_raw_response'
                   AND NOT EXISTS (
                       SELECT 1
                       FROM public.grading_attempts a
                       WHERE a.id = current_object.source_record_id
                         AND a.owner_id = current_object.owner_id
                         AND a.raw_response_object_key = current_object.object_key
                   )
               ) THEN
                UPDATE public.retention_objects
                SET status = 'invalidated',
                    claim_token = NULL,
                    lease_expires_at = NULL,
                    last_error_code = 'retention_candidate_invalidated',
                    updated_at = pg_catalog.transaction_timestamp()
                WHERE id = p_object_id;
                RETURN 'ineligible';
            END IF;
            RETURN 'eligible';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.complete_retention_object(
            p_object_id uuid,
            p_claim_token uuid,
            p_storage_result text
        )
        RETURNS public.retention_objects
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            completed public.retention_objects%ROWTYPE;
        BEGIN
            IF p_storage_result NOT IN ('deleted', 'missing') THEN
                RETURN NULL;
            END IF;
            UPDATE public.retention_objects
            SET status = 'completed',
                claim_token = NULL,
                lease_expires_at = NULL,
                last_error_code = NULL,
                storage_result = p_storage_result,
                deleted_at = pg_catalog.transaction_timestamp(),
                completed_at = pg_catalog.transaction_timestamp(),
                updated_at = pg_catalog.transaction_timestamp()
            WHERE id = p_object_id
              AND status = 'running'
              AND claim_token = p_claim_token
              AND lease_expires_at > pg_catalog.transaction_timestamp()
            RETURNING * INTO completed;
            RETURN completed;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.fail_retention_object(
            p_object_id uuid,
            p_claim_token uuid,
            p_error_code text
        )
        RETURNS public.retention_objects
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            failed public.retention_objects%ROWTYPE;
        BEGIN
            IF p_error_code IS NULL OR btrim(p_error_code) = '' THEN
                RETURN NULL;
            END IF;
            UPDATE public.retention_objects
            SET status = 'failed',
                claim_token = NULL,
                lease_expires_at = NULL,
                next_attempt_at = pg_catalog.transaction_timestamp()
                    + pg_catalog.make_interval(secs => 300),
                last_error_code = p_error_code,
                updated_at = pg_catalog.transaction_timestamp()
            WHERE id = p_object_id
              AND status = 'running'
              AND claim_token = p_claim_token
              AND lease_expires_at > pg_catalog.transaction_timestamp()
            RETURNING * INTO failed;
            RETURN failed;
        END;
        $$
        """
    )
    for signature in (
        "paper_grading_private.list_retention_candidates(integer)",
        "paper_grading_private.claim_next_retention_object(uuid, integer)",
        "paper_grading_private.revalidate_retention_object(uuid, uuid)",
        "paper_grading_private.complete_retention_object(uuid, uuid, text)",
        "paper_grading_private.fail_retention_object(uuid, uuid, text)",
    ):
        _revoke_execute(signature)
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {RETENTION_WORKER_ROLE}")


def _apply_table_security() -> None:
    internal_tables = (
        "quota_resource_states",
        "quota_reservations",
        "quota_alerts",
        "retention_policies",
        "retention_objects",
        "backup_policies",
        "backup_runs",
        "backup_restore_runs",
    )
    for table in internal_tables:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")
        for role in API_ROLES + ("paper_grading_teacher_api",):
            op.execute(f"REVOKE ALL ON TABLE public.{table} FROM {role}")
    op.execute(
        f"GRANT SELECT ON TABLE public.retention_objects, public.retention_policies "
        f"TO {RETENTION_WORKER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT ON TABLE public.backup_runs, public.backup_restore_runs, "
        f"public.backup_policies TO {BACKUP_WORKER_ROLE}"
    )


def upgrade() -> None:
    _create_roles()
    _create_tables()
    _create_quota_functions()
    _create_retention_functions()
    _apply_table_security()


def downgrade() -> None:
    """仅在尚无阶段十三审计历史时回退。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.quota_reservations LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.quota_alerts LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.retention_objects LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.backup_runs LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.backup_restore_runs LIMIT 1) THEN
                RAISE EXCEPTION 'cannot remove stage thirteen while lifecycle history exists';
            END IF;
        END;
        $paper_grading$
        """
    )
    for signature in (
        "paper_grading_private.fail_retention_object(uuid, uuid, text)",
        "paper_grading_private.complete_retention_object(uuid, uuid, text)",
        "paper_grading_private.revalidate_retention_object(uuid, uuid)",
        "paper_grading_private.claim_next_retention_object(uuid, integer)",
        "paper_grading_private.list_retention_candidates(integer)",
        "paper_grading_private.finalize_storage_growth(uuid, text)",
        "paper_grading_private.reserve_storage_growth(text, text, bytea, bigint)",
        "paper_grading_private.check_database_growth(text, bigint)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    for table in (
        "backup_restore_runs",
        "backup_runs",
        "backup_policies",
        "retention_objects",
        "retention_policies",
        "quota_alerts",
        "quota_reservations",
        "quota_resource_states",
    ):
        op.drop_table(table)
    for role in (BACKUP_WORKER_ROLE, RETENTION_WORKER_ROLE):
        op.execute(f"REVOKE USAGE ON SCHEMA public, paper_grading_private FROM {role}")
        op.execute(f"REVOKE {role} FROM postgres")
        op.execute(f"DROP ROLE IF EXISTS {role}")
