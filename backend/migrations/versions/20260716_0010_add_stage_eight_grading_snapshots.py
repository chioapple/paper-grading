"""add stage eight grading contract snapshots

Revision ID: 20260716_0010
Revises: 20260716_0009
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0010"
down_revision: str | None = "20260716_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_PROTECT_FUNCTION = "public.paper_grading_protect_job_snapshot()"
ATTEMPT_PROTECT_FUNCTION = "public.paper_grading_protect_attempt_history()"
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


def _create_job_protect_function(*, stage_eight: bool) -> None:
    new_snapshot_fields = (
        """
                NEW.result_schema_version,
                NEW.result_schema_hash,
                NEW.rubric_hash,"""
        if stage_eight
        else ""
    )
    old_snapshot_fields = (
        """
                OLD.result_schema_version,
                OLD.result_schema_hash,
                OLD.rubric_hash,"""
        if stage_eight
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
                NEW.provider_config_id,
                NEW.model,
                NEW.model_parameters,
                NEW.prompt_version,
                NEW.prompt_hash,{new_snapshot_fields}
                NEW.idempotency_key,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.assignment_id,
                OLD.rubric_version_id,
                OLD.provider_config_id,
                OLD.model,
                OLD.model_parameters,
                OLD.prompt_version,
                OLD.prompt_hash,{old_snapshot_fields}
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


def _create_attempt_protect_function(*, stage_eight: bool) -> None:
    new_request_version = "NEW.request_version," if stage_eight else ""
    old_request_version = "OLD.request_version," if stage_eight else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_protect_attempt_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'grading attempt history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status <> 'running' OR NEW.status = 'running' THEN
                RAISE EXCEPTION 'grading attempt can only leave running once'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                NEW.id,
                NEW.owner_id,
                NEW.grading_job_item_id,
                NEW.attempt_number,
                {new_request_version}
                NEW.request_hash,
                NEW.idempotency_key,
                NEW.max_score,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.grading_job_item_id,
                OLD.attempt_number,
                {old_request_version}
                OLD.request_hash,
                OLD.idempotency_key,
                OLD.max_score,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'grading attempt identity and input are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_api_execute(ATTEMPT_PROTECT_FUNCTION)


def upgrade() -> None:
    """保存阶段八评分契约的版本与哈希。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.grading_jobs LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.grading_attempts LIMIT 1) THEN
                RAISE EXCEPTION 'stage eight requires empty grading job tables';
            END IF;
        END;
        $paper_grading$
        """
    )
    op.add_column(
        "grading_jobs",
        sa.Column("result_schema_version", sa.Text(), nullable=False),
    )
    op.add_column(
        "grading_jobs",
        sa.Column("result_schema_hash", sa.LargeBinary(length=32), nullable=False),
    )
    op.add_column(
        "grading_jobs",
        sa.Column("rubric_hash", sa.LargeBinary(length=32), nullable=False),
    )
    op.add_column(
        "grading_attempts",
        sa.Column("request_version", sa.Text(), nullable=False),
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
    op.drop_constraint(
        op.f("grading_attempts_request_check"),
        "grading_attempts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("grading_attempts_request_check"),
        "grading_attempts",
        "btrim(request_version) <> '' and octet_length(request_hash) = 32 "
        "and btrim(idempotency_key) <> ''",
    )
    _create_job_protect_function(stage_eight=True)
    _create_attempt_protect_function(stage_eight=True)


def downgrade() -> None:
    """移除阶段八评分契约快照。"""

    _create_job_protect_function(stage_eight=False)
    _create_attempt_protect_function(stage_eight=False)
    op.drop_constraint(
        op.f("grading_attempts_request_check"),
        "grading_attempts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("grading_attempts_request_check"),
        "grading_attempts",
        "octet_length(request_hash) = 32 and btrim(idempotency_key) <> ''",
    )
    op.drop_constraint(op.f("grading_jobs_snapshot_check"), "grading_jobs", type_="check")
    op.create_check_constraint(
        op.f("grading_jobs_snapshot_check"),
        "grading_jobs",
        "btrim(model) <> '' and btrim(prompt_version) <> '' "
        "and octet_length(prompt_hash) = 32 and btrim(idempotency_key) <> ''",
    )
    op.drop_column("grading_attempts", "request_version")
    op.drop_column("grading_jobs", "rubric_hash")
    op.drop_column("grading_jobs", "result_schema_hash")
    op.drop_column("grading_jobs", "result_schema_version")
