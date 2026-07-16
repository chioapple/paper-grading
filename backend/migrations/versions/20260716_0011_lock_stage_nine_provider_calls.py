"""lock stage nine provider call snapshots

Revision ID: 20260716_0011
Revises: 20260716_0010
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_0011"
down_revision: str | None = "20260716_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_PROTECT_FUNCTION = "public.paper_grading_protect_job_snapshot()"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")


def _revoke_api_execute(function_signature: str) -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION {function_signature} FROM PUBLIC")
    roles = ", ".join(f"'{role}'" for role in SUPABASE_API_ROLES)
    op.execute(
        f"""
        DO $paper_grading$
        DECLARE
            target_role text;
        BEGIN
            FOR target_role IN
                SELECT rolname
                FROM pg_catalog.pg_roles
                WHERE rolname IN ({roles})
            LOOP
                EXECUTE pg_catalog.format(
                    'REVOKE EXECUTE ON FUNCTION {function_signature} FROM %I',
                    target_role
                );
            END LOOP;
        END;
        $paper_grading$
        """
    )


def _create_job_protect_function(*, stage_nine: bool) -> None:
    new_stage_nine_fields = (
        """
                NEW.provider_config_version,
                NEW.result_schema,"""
        if stage_nine
        else ""
    )
    old_stage_nine_fields = (
        """
                OLD.provider_config_version,
                OLD.result_schema,"""
        if stage_nine
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_protect_job_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'grading job history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                NEW.id,
                NEW.owner_id,
                NEW.assignment_id,
                NEW.rubric_version_id,
                NEW.provider_config_id,{new_stage_nine_fields}
                NEW.model,
                NEW.model_parameters,
                NEW.prompt_version,
                NEW.prompt_hash,
                NEW.result_schema_version,
                NEW.result_schema_hash,
                NEW.rubric_hash,
                NEW.idempotency_key,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.assignment_id,
                OLD.rubric_version_id,
                OLD.provider_config_id,{old_stage_nine_fields}
                OLD.model,
                OLD.model_parameters,
                OLD.prompt_version,
                OLD.prompt_hash,
                OLD.result_schema_version,
                OLD.result_schema_hash,
                OLD.rubric_hash,
                OLD.idempotency_key,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'grading job input snapshot is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT (
                (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
                OR (OLD.status = 'running' AND NEW.status IN (
                    'paused', 'needs_review', 'completed', 'failed', 'cancelled'
                ))
                OR (OLD.status = 'paused' AND NEW.status IN ('running', 'cancelled'))
                OR (OLD.status = 'needs_review' AND NEW.status IN (
                    'completed', 'failed', 'cancelled'
                ))
            ) THEN
                RAISE EXCEPTION 'invalid grading job status transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_api_execute(JOB_PROTECT_FUNCTION)


def upgrade() -> None:
    """锁定供应商配置版本、Schema 正文和原始响应哈希。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.grading_jobs LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.grading_attempts LIMIT 1) THEN
                RAISE EXCEPTION 'stage nine requires empty grading job tables';
            END IF;
        END;
        $paper_grading$
        """
    )
    op.add_column(
        "grading_jobs",
        sa.Column("provider_config_version", sa.Integer(), nullable=False),
    )
    op.add_column(
        "grading_jobs",
        sa.Column(
            "result_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
    )
    op.add_column(
        "grading_attempts",
        sa.Column("raw_response_sha256", sa.LargeBinary(length=32), nullable=True),
    )
    op.drop_constraint(op.f("grading_jobs_snapshot_check"), "grading_jobs", type_="check")
    op.create_check_constraint(
        op.f("grading_jobs_snapshot_check"),
        "grading_jobs",
        "provider_config_version > 0 and btrim(model) <> '' "
        "and jsonb_typeof(result_schema) = 'object' "
        "and btrim(prompt_version) <> '' and octet_length(prompt_hash) = 32 "
        "and btrim(result_schema_version) <> '' "
        "and octet_length(result_schema_hash) = 32 "
        "and octet_length(rubric_hash) = 32 "
        "and btrim(idempotency_key) <> ''",
    )
    op.create_check_constraint(
        op.f("grading_attempts_raw_response_check"),
        "grading_attempts",
        "((raw_response_object_key is null) = (raw_response_sha256 is null)) "
        "and (raw_response_sha256 is null or octet_length(raw_response_sha256) = 32)",
    )
    _create_job_protect_function(stage_nine=True)


def downgrade() -> None:
    """恢复阶段八供应商调用快照。"""

    _create_job_protect_function(stage_nine=False)
    op.drop_constraint(
        op.f("grading_attempts_raw_response_check"),
        "grading_attempts",
        type_="check",
    )
    op.drop_constraint(op.f("grading_jobs_snapshot_check"), "grading_jobs", type_="check")
    op.create_check_constraint(
        op.f("grading_jobs_snapshot_check"),
        "grading_jobs",
        "btrim(model) <> '' and btrim(prompt_version) <> '' "
        "and octet_length(prompt_hash) = 32 "
        "and btrim(result_schema_version) <> '' "
        "and octet_length(result_schema_hash) = 32 "
        "and octet_length(rubric_hash) = 32 "
        "and btrim(idempotency_key) <> ''",
    )
    op.drop_column("grading_attempts", "raw_response_sha256")
    op.drop_column("grading_jobs", "result_schema")
    op.drop_column("grading_jobs", "provider_config_version")
