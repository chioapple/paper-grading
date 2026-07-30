"""建立阶段十可恢复、可追踪、可审计的批量评分状态机。

Revision ID: 20260716_0012
Revises: 20260716_0011
Create Date: 2026-07-16
"""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260716_0012"
down_revision = "20260716_0011"
branch_labels = None
depends_on = None

WORKER_ROLE = "paper_grading_worker"
API_ROLES = ("PUBLIC", "anon", "authenticated", "service_role")


def _revoke_execute(signature: str, roles: Iterable[str] = API_ROLES) -> None:
    for role in roles:
        if role == "PUBLIC":
            op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC")
            continue
        op.execute(
            f"""
            DO $paper_grading$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE EXECUTE ON FUNCTION {signature} FROM {role};
                END IF;
            END;
            $paper_grading$
            """
        )


def _create_provider_invalidation_function(*, stage_ten: bool) -> None:
    model_profile_field = ",\n                NEW.model_profiles" if stage_ten else ""
    old_model_profile_field = ",\n                OLD.model_profiles" if stage_ten else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_invalidate_provider_test()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF ROW(
                NEW.provider_type,
                NEW.base_url,
                NEW.encrypted_api_key,
                NEW.api_key_nonce,
                NEW.allowed_models,
                NEW.default_model,
                NEW.timeout_seconds{model_profile_field}
            ) IS DISTINCT FROM ROW(
                OLD.provider_type,
                OLD.base_url,
                OLD.encrypted_api_key,
                OLD.api_key_nonce,
                OLD.allowed_models,
                OLD.default_model,
                OLD.timeout_seconds{old_model_profile_field}
            ) THEN
                NEW.config_version := OLD.config_version + 1;
                NEW.tested_at := NULL;
                NEW.tested_config_version := NULL;
                NEW.status := 'draft';
            ELSE
                NEW.config_version := OLD.config_version;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_invalidate_provider_test()")


def _create_job_protection_function(*, stage_ten: bool) -> None:
    new_fields = (
        """
                NEW.assignment_title_snapshot,
                NEW.assignment_instructions_snapshot,
                NEW.expected_item_count,
                NEW.request_hash,
                NEW.model_parameters_hash,"""
        if stage_ten
        else ""
    )
    old_fields = (
        """
                OLD.assignment_title_snapshot,
                OLD.assignment_instructions_snapshot,
                OLD.expected_item_count,
                OLD.request_hash,
                OLD.model_parameters_hash,"""
        if stage_ten
        else ""
    )
    reopening = (
        """
                OR (OLD.status IN ('needs_review', 'completed', 'failed')
                    AND NEW.status = 'running')"""
        if stage_ten
        else ""
    )
    same_status = "(OLD.status = NEW.status) OR" if stage_ten else ""
    paused_targets = (
        "'running', 'needs_review', 'completed', 'failed', 'cancelled'"
        if stage_ten
        else "'running', 'cancelled'"
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
                NEW.provider_config_version,{new_fields}
                NEW.result_schema,
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
                OLD.provider_config_id,
                OLD.provider_config_version,{old_fields}
                OLD.result_schema,
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
                {same_status}
                (OLD.status = 'queued' AND NEW.status IN ('running', 'paused', 'cancelled'))
                OR (OLD.status = 'running' AND NEW.status IN (
                    'paused', 'needs_review', 'completed', 'failed', 'cancelled'
                ))
                OR (OLD.status = 'paused' AND NEW.status IN ({paused_targets}))
                OR (OLD.status = 'needs_review' AND NEW.status IN (
                    'completed', 'failed', 'cancelled'
                )){reopening}
            ) THEN
                RAISE EXCEPTION 'invalid grading job status transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_protect_job_snapshot()")


def _create_attempt_protection_function(*, stage_ten: bool) -> None:
    new_fields = (
        """
                NEW.parent_attempt_id,
                NEW.scoring_round,
                NEW.call_sequence,
                NEW.attempt_kind,
                NEW.provider_call_started_at,"""
        if stage_ten
        else ""
    )
    old_fields = (
        """
                OLD.parent_attempt_id,
                OLD.scoring_round,
                OLD.call_sequence,
                OLD.attempt_kind,
                OLD.provider_call_started_at,"""
        if stage_ten
        else ""
    )
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
                NEW.attempt_number,{new_fields}
                NEW.request_version,
                NEW.request_hash,
                NEW.idempotency_key,
                NEW.max_score,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.grading_job_item_id,
                OLD.attempt_number,{old_fields}
                OLD.request_version,
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
    _revoke_execute("public.paper_grading_protect_attempt_history()")


def _add_columns() -> None:
    op.add_column(
        "provider_configs",
        sa.Column(
            "model_profiles",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    for column in (
        sa.Column("assignment_title_snapshot", sa.Text(), nullable=False),
        sa.Column("assignment_instructions_snapshot", sa.Text(), nullable=False),
        sa.Column("expected_item_count", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("model_parameters_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("state_version", sa.BigInteger(), server_default=sa.text("'1'"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ):
        op.add_column("grading_jobs", column)

    for column in (
        sa.Column("dispatch_version", sa.Integer(), server_default=sa.text("'1'"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("'0'"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ):
        op.add_column("grading_job_items", column)

    attempt_columns = (
        sa.Column("parent_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("scoring_round", sa.Integer(), nullable=False),
        sa.Column("call_sequence", sa.Integer(), nullable=False),
        sa.Column("attempt_kind", sa.Text(), nullable=False),
        sa.Column("provider_call_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "provider_call_state",
            sa.Text(),
            server_default=sa.text("'started'"),
            nullable=False,
        ),
        sa.Column("provider_request_id", sa.Text(), nullable=True),
        sa.Column("reported_model", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Numeric(10, 4), nullable=True),
        sa.Column("deduction_total", sa.Numeric(10, 4), nullable=True),
        sa.Column("deduction_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_write_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("estimated_cost_amount", sa.Numeric(18, 9), nullable=True),
        sa.Column("cost_currency", sa.Text(), nullable=True),
        sa.Column("tariff_version", sa.Text(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    for column in attempt_columns:
        op.add_column("grading_attempts", column)


def _replace_constraints() -> None:
    op.create_check_constraint(
        op.f("provider_configs_model_profiles_check"),
        "provider_configs",
        "jsonb_typeof(model_profiles) = 'object'",
    )

    op.drop_constraint(op.f("grading_jobs_snapshot_check"), "grading_jobs", type_="check")
    op.create_check_constraint(
        op.f("grading_jobs_snapshot_check"),
        "grading_jobs",
        "provider_config_version > 0 and btrim(model) <> '' "
        "and jsonb_typeof(result_schema) = 'object' "
        "and octet_length(request_hash) = 32 and octet_length(model_parameters_hash) = 32 "
        "and btrim(prompt_version) <> '' and octet_length(prompt_hash) = 32 "
        "and btrim(result_schema_version) <> '' and octet_length(result_schema_hash) = 32 "
        "and octet_length(rubric_hash) = 32 and btrim(idempotency_key) <> ''",
    )
    op.create_check_constraint(
        op.f("grading_jobs_progress_check"),
        "grading_jobs",
        "expected_item_count between 1 and 100 and state_version > 0",
    )
    op.create_check_constraint(
        op.f("grading_jobs_assignment_snapshot_check"),
        "grading_jobs",
        "btrim(assignment_title_snapshot) <> '' and btrim(assignment_instructions_snapshot) <> ''",
    )

    op.create_check_constraint(
        op.f("grading_job_items_delivery_check"),
        "grading_job_items",
        "dispatch_version > 0 and retry_count >= 0",
    )
    op.create_check_constraint(
        op.f("grading_job_items_state_check"),
        "grading_job_items",
        "(status = 'queued' and finished_at is null and lease_token is null "
        "and lease_expires_at is null and error_code is null) or "
        "(status = 'running' and started_at is not null and finished_at is null "
        "and lease_token is not null and lease_expires_at is not null and error_code is null) or "
        "(status = 'needs_review' and finished_at is not null "
        "and lease_token is null and lease_expires_at is null "
        "and (error_code is null or btrim(error_code) <> '')) or "
        "(status = 'completed' and finished_at is not null "
        "and lease_token is null and lease_expires_at is null and error_code is null) or "
        "(status = 'failed' and finished_at is not null and lease_token is null "
        "and lease_expires_at is null and btrim(error_code) <> '') or "
        "(status = 'cancelled' and finished_at is not null and lease_token is null "
        "and lease_expires_at is null)",
    )

    op.create_unique_constraint(
        op.f("grading_attempts_grading_job_item_id_scoring_round_call_sequence_key"),
        "grading_attempts",
        ["grading_job_item_id", "scoring_round", "call_sequence"],
    )
    op.create_foreign_key(
        op.f("grading_attempts_parent_item_owner_fkey"),
        "grading_attempts",
        "grading_attempts",
        ["parent_attempt_id", "grading_job_item_id", "owner_id"],
        ["id", "grading_job_item_id", "owner_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("grading_attempts_call_position_check"),
        "grading_attempts",
        "scoring_round > 0 and call_sequence > 0",
    )
    op.create_check_constraint(
        op.f("grading_attempts_attempt_kind_check"),
        "grading_attempts",
        "attempt_kind in ('initial', 'correction', 'automatic_retry', 'manual_retry')",
    )
    op.create_check_constraint(
        op.f("grading_attempts_provider_call_state_check"),
        "grading_attempts",
        "provider_call_state in ('started', 'not_sent', 'response_received', 'ambiguous')",
    )
    op.create_check_constraint(
        op.f("grading_attempts_deduction_results_check"),
        "grading_attempts",
        "deduction_results is null or jsonb_typeof(deduction_results) = 'array'",
    )
    op.create_check_constraint(
        op.f("grading_attempts_error_details_check"),
        "grading_attempts",
        "error_details is null or jsonb_typeof(error_details) = 'object'",
    )
    op.create_check_constraint(
        op.f("grading_attempts_token_usage_check"),
        "grading_attempts",
        "(input_tokens is null and cached_input_tokens is null "
        "and cache_write_input_tokens is null and output_tokens is null "
        "and reasoning_tokens is null and total_tokens is null) or "
        "(input_tokens >= 0 and cached_input_tokens >= 0 and cache_write_input_tokens >= 0 "
        "and output_tokens >= 0 and reasoning_tokens >= 0 "
        "and (total_tokens is null or total_tokens >= 0) "
        "and cached_input_tokens + cache_write_input_tokens <= input_tokens "
        "and reasoning_tokens <= output_tokens)",
    )
    op.create_check_constraint(
        op.f("grading_attempts_cost_check"),
        "grading_attempts",
        "(estimated_cost_amount is null and cost_currency is null and tariff_version is null) "
        "or (estimated_cost_amount >= 0 and cost_currency ~ '^[A-Z]{3}$' "
        "and btrim(tariff_version) <> '')",
    )
    op.drop_constraint(op.f("grading_attempts_result_check"), "grading_attempts", type_="check")
    op.create_check_constraint(
        op.f("grading_attempts_result_check"),
        "grading_attempts",
        "(status = 'running' and finished_at is null) or "
        "(status in ('succeeded', 'needs_review') and finished_at is not null "
        "and provider_call_state = 'response_received' and total_score is not null "
        "and subtotal is not null and deduction_total is not null "
        "and total_score = greatest(0, subtotal - deduction_total) "
        "and criteria_results is not null and deduction_results is not null "
        "and overall_feedback is not null and raw_response_object_key is not null "
        "and provider_request_id is not null and reported_model is not null "
        "and input_tokens is not null) or "
        "(status = 'failed' and finished_at is not null and error_code is not null)",
    )


def _create_indexes() -> None:
    op.create_index(
        "grading_job_items_dispatch_idx",
        "grading_job_items",
        ["available_at", "created_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "grading_job_items_expired_lease_idx",
        "grading_job_items",
        ["lease_expires_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "grading_attempts_parent_item_owner_idx",
        "grading_attempts",
        ["parent_attempt_id", "grading_job_item_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "grading_attempts_one_running_idx",
        "grading_attempts",
        ["grading_job_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "grading_attempts_raw_response_object_key_idx",
        "grading_attempts",
        ["raw_response_object_key"],
        unique=True,
        postgresql_where=sa.text("raw_response_object_key is not null"),
    )


def _create_stage_ten_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION public.paper_grading_guard_provider_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF ROW(
                NEW.provider_type, NEW.base_url, NEW.encrypted_api_key, NEW.api_key_nonce,
                NEW.allowed_models, NEW.default_model, NEW.timeout_seconds, NEW.model_profiles
            ) IS DISTINCT FROM ROW(
                OLD.provider_type, OLD.base_url, OLD.encrypted_api_key, OLD.api_key_nonce,
                OLD.allowed_models, OLD.default_model, OLD.timeout_seconds, OLD.model_profiles
            ) AND EXISTS (
                SELECT 1 FROM public.grading_jobs AS job
                WHERE job.provider_config_id = OLD.id
                  AND job.status IN ('queued', 'running', 'paused')
            ) THEN
                RAISE EXCEPTION 'provider configuration has active grading jobs'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_guard_provider_update()")
    op.execute(
        """
        CREATE TRIGGER provider_configs_guard_active_jobs
        BEFORE UPDATE ON public.provider_configs
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_guard_provider_update()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_require_ready_job_item()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        DECLARE
            target_job public.grading_jobs%ROWTYPE;
            target_submission public.submissions%ROWTYPE;
        BEGIN
            SELECT * INTO target_job
            FROM public.grading_jobs
            WHERE id = NEW.grading_job_id
              AND assignment_id = NEW.assignment_id
              AND owner_id = NEW.owner_id
            FOR UPDATE;
            IF NOT FOUND OR target_job.status <> 'queued' THEN
                RAISE EXCEPTION 'grading job item requires a queued job'
                    USING ERRCODE = '23514';
            END IF;
            SELECT * INTO target_submission
            FROM public.submissions
            WHERE id = NEW.submission_id
              AND assignment_id = NEW.assignment_id
              AND owner_id = NEW.owner_id
            FOR SHARE;
            IF NOT FOUND OR target_submission.status <> 'ready' THEN
                RAISE EXCEPTION 'grading job item requires a ready submission'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.position >= target_job.expected_item_count THEN
                RAISE EXCEPTION 'grading job item position exceeds expected count'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_require_ready_job_item()")
    op.execute(
        """
        CREATE TRIGGER grading_job_items_require_ready
        BEFORE INSERT ON public.grading_job_items
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_require_ready_job_item()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_validate_job_item_count()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        DECLARE
            target_job_id uuid;
            expected_count integer;
            actual_count integer;
        BEGIN
            target_job_id := CASE
                WHEN TG_TABLE_NAME = 'grading_jobs' THEN NEW.id
                ELSE NEW.grading_job_id
            END;
            SELECT expected_item_count INTO expected_count
            FROM public.grading_jobs WHERE id = target_job_id;
            SELECT count(*) INTO actual_count
            FROM public.grading_job_items WHERE grading_job_id = target_job_id;
            IF expected_count IS NULL OR actual_count <> expected_count THEN
                RAISE EXCEPTION 'grading job item count does not match expected count'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_validate_job_item_count()")
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER grading_jobs_validate_item_count
        AFTER INSERT ON public.grading_jobs
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_validate_job_item_count()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER grading_job_items_validate_job_count
        AFTER INSERT ON public.grading_job_items
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_validate_job_item_count()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_protect_job_item()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'grading job item history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                NEW.id, NEW.owner_id, NEW.assignment_id, NEW.grading_job_id,
                NEW.submission_id, NEW.position, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.owner_id, OLD.assignment_id, OLD.grading_job_id,
                OLD.submission_id, OLD.position, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'grading job item identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT (
                (OLD.status = 'queued' AND NEW.status IN ('running', 'cancelled'))
                OR (OLD.status = 'running' AND NEW.status IN (
                    'queued', 'needs_review', 'completed', 'failed', 'cancelled'
                ))
                OR (OLD.status IN ('needs_review', 'completed', 'failed')
                    AND NEW.status = 'queued')
            ) THEN
                RAISE EXCEPTION 'invalid grading job item status transition'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status IN ('needs_review', 'completed', 'failed') AND NEW.status = 'queued' THEN
                IF NEW.dispatch_version <> OLD.dispatch_version + 1 OR NEW.retry_count <> 0 THEN
                    RAISE EXCEPTION 'manual retry must advance dispatch version'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF OLD.status = 'running' AND NEW.status = 'queued' THEN
                IF NEW.dispatch_version <> OLD.dispatch_version
                   OR NEW.retry_count <> OLD.retry_count + 1 THEN
                    RAISE EXCEPTION 'automatic retry must advance retry count only'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF NEW.dispatch_version <> OLD.dispatch_version
                  OR NEW.retry_count <> OLD.retry_count THEN
                RAISE EXCEPTION 'delivery version changed outside retry transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_protect_job_item()")
    op.execute(
        """
        CREATE TRIGGER grading_job_items_protect_history
        BEFORE UPDATE OR DELETE ON public.grading_job_items
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_protect_job_item()
        """
    )

    op.execute(
        """
        CREATE FUNCTION paper_grading_private.control_grading_job(
            target_job_id uuid,
            action text,
            target_item_id uuid DEFAULT NULL
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            teacher_id uuid;
            current_job public.grading_jobs%ROWTYPE;
        BEGIN
            teacher_id := paper_grading_private.current_active_teacher_id();
            IF teacher_id IS NULL THEN
                RETURN NULL;
            END IF;
            SELECT * INTO current_job
            FROM public.grading_jobs
            WHERE id = target_job_id AND owner_id = teacher_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            IF action = 'pause' AND current_job.status IN ('queued', 'running') THEN
                UPDATE public.grading_jobs
                SET status = 'paused', started_at = COALESCE(started_at, now()),
                    state_version = state_version + 1, updated_at = now()
                WHERE id = target_job_id;
            ELSIF action = 'resume' AND current_job.status = 'paused' THEN
                UPDATE public.grading_jobs
                SET status = 'running', state_version = state_version + 1, updated_at = now()
                WHERE id = target_job_id;
            ELSIF action = 'cancel'
                  AND current_job.status IN ('queued', 'running', 'paused', 'needs_review') THEN
                UPDATE public.grading_job_items
                SET status = 'cancelled', finished_at = now(), updated_at = now()
                WHERE grading_job_id = target_job_id AND owner_id = teacher_id
                  AND status = 'queued';
                UPDATE public.grading_jobs
                SET status = 'cancelled', started_at = COALESCE(started_at, now()),
                    finished_at = now(), state_version = state_version + 1, updated_at = now()
                WHERE id = target_job_id;
            ELSIF action = 'retry' AND target_item_id IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM public.provider_configs AS provider
                    WHERE provider.id = current_job.provider_config_id
                      AND provider.config_version = current_job.provider_config_version
                ) THEN
                    RETURN NULL;
                END IF;
                UPDATE public.grading_job_items
                SET status = 'queued', dispatch_version = dispatch_version + 1,
                    retry_count = 0, available_at = now(), lease_token = NULL,
                    lease_expires_at = NULL, started_at = NULL, finished_at = NULL,
                    error_code = NULL, updated_at = now()
                WHERE id = target_item_id AND grading_job_id = target_job_id
                  AND owner_id = teacher_id AND status IN ('needs_review', 'completed', 'failed');
                IF NOT FOUND THEN
                    RETURN NULL;
                END IF;
                UPDATE public.grading_jobs
                SET status = 'running', started_at = COALESCE(started_at, now()),
                    finished_at = NULL, state_version = state_version + 1, updated_at = now()
                WHERE id = target_job_id;
            ELSE
                RETURN NULL;
            END IF;
            RETURN target_job_id;
        END;
        $$
        """
    )
    _revoke_execute("paper_grading_private.control_grading_job(uuid, text, uuid)")
    op.execute(
        "GRANT EXECUTE ON FUNCTION paper_grading_private.control_grading_job(uuid, text, uuid) "
        "TO paper_grading_teacher_api"
    )


def _create_worker_role() -> None:
    op.execute(
        f"""
        DO $paper_grading$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{WORKER_ROLE}') THEN
                CREATE ROLE {WORKER_ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
        END;
        $paper_grading$
        """
    )
    op.execute(f"ALTER ROLE {WORKER_ROLE} NOLOGIN NOINHERIT NOBYPASSRLS")
    op.execute(f"GRANT {WORKER_ROLE} TO postgres")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {WORKER_ROLE}")
    op.execute(
        f"GRANT SELECT ON TABLE public.provider_configs, public.assignments, "
        f"public.rubric_versions, public.submissions TO {WORKER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT, UPDATE ON TABLE public.grading_jobs, public.grading_job_items "
        f"TO {WORKER_ROLE}"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON TABLE public.grading_attempts TO {WORKER_ROLE}")
    for table_name in (
        "provider_configs",
        "assignments",
        "rubric_versions",
        "submissions",
        "grading_jobs",
        "grading_job_items",
        "grading_attempts",
    ):
        op.execute(
            f"CREATE POLICY {table_name}_worker_all ON public.{table_name} "
            f"FOR ALL TO {WORKER_ROLE} USING (true) WITH CHECK (true)"
        )


def upgrade() -> None:
    """扩展现有评分表并建立批次、Worker 和重试状态边界。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.grading_jobs LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.grading_job_items LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.grading_attempts LIMIT 1) THEN
                RAISE EXCEPTION 'stage ten requires empty grading job tables';
            END IF;
        END;
        $paper_grading$
        """
    )
    _add_columns()
    _replace_constraints()
    _create_indexes()
    _create_provider_invalidation_function(stage_ten=True)
    _create_job_protection_function(stage_ten=True)
    _create_attempt_protection_function(stage_ten=True)
    _create_stage_ten_functions()
    _create_worker_role()


def _drop_worker_role() -> None:
    for table_name in reversed(
        (
            "provider_configs",
            "assignments",
            "rubric_versions",
            "submissions",
            "grading_jobs",
            "grading_job_items",
            "grading_attempts",
        )
    ):
        op.execute(f"DROP POLICY {table_name}_worker_all ON public.{table_name}")
    op.execute(f"REVOKE {WORKER_ROLE} FROM postgres")
    op.execute(f"DROP ROLE IF EXISTS {WORKER_ROLE}")


def downgrade() -> None:
    """恢复阶段九评分表和供应商配置结构。"""

    _drop_worker_role()
    op.execute("DROP FUNCTION paper_grading_private.control_grading_job(uuid, text, uuid)")
    op.execute("DROP TRIGGER grading_job_items_protect_history ON public.grading_job_items")
    op.execute("DROP TRIGGER grading_job_items_validate_job_count ON public.grading_job_items")
    op.execute("DROP TRIGGER grading_jobs_validate_item_count ON public.grading_jobs")
    op.execute("DROP TRIGGER grading_job_items_require_ready ON public.grading_job_items")
    op.execute("DROP FUNCTION public.paper_grading_protect_job_item()")
    op.execute("DROP FUNCTION public.paper_grading_validate_job_item_count()")
    op.execute("DROP FUNCTION public.paper_grading_require_ready_job_item()")
    op.execute("DROP TRIGGER provider_configs_guard_active_jobs ON public.provider_configs")
    op.execute("DROP FUNCTION public.paper_grading_guard_provider_update()")

    _create_provider_invalidation_function(stage_ten=False)
    _create_job_protection_function(stage_ten=False)
    _create_attempt_protection_function(stage_ten=False)

    for index_name in (
        "grading_attempts_raw_response_object_key_idx",
        "grading_attempts_one_running_idx",
        "grading_attempts_parent_item_owner_idx",
        "grading_job_items_expired_lease_idx",
        "grading_job_items_dispatch_idx",
    ):
        op.drop_index(index_name)

    op.drop_constraint(op.f("grading_attempts_result_check"), "grading_attempts", type_="check")
    for constraint_name, constraint_type in (
        ("grading_attempts_cost_check", "check"),
        ("grading_attempts_token_usage_check", "check"),
        ("grading_attempts_error_details_check", "check"),
        ("grading_attempts_deduction_results_check", "check"),
        ("grading_attempts_provider_call_state_check", "check"),
        ("grading_attempts_attempt_kind_check", "check"),
        ("grading_attempts_call_position_check", "check"),
        ("grading_attempts_parent_item_owner_fkey", "foreignkey"),
        ("grading_attempts_grading_job_item_id_scoring_round_call_sequence_key", "unique"),
    ):
        op.drop_constraint(op.f(constraint_name), "grading_attempts", type_=constraint_type)
    op.create_check_constraint(
        op.f("grading_attempts_result_check"),
        "grading_attempts",
        "(status = 'running' and finished_at is null) or "
        "(status in ('succeeded', 'needs_review') and finished_at is not null "
        "and total_score is not null and criteria_results is not null "
        "and overall_feedback is not null and raw_response_object_key is not null) or "
        "(status = 'failed' and finished_at is not null and error_code is not null)",
    )

    for column_name in reversed(
        (
            "parent_attempt_id",
            "scoring_round",
            "call_sequence",
            "attempt_kind",
            "provider_call_started_at",
            "provider_call_state",
            "provider_request_id",
            "reported_model",
            "subtotal",
            "deduction_total",
            "deduction_results",
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "estimated_cost_amount",
            "cost_currency",
            "tariff_version",
            "error_details",
        )
    ):
        op.drop_column("grading_attempts", column_name)

    op.drop_constraint(op.f("grading_job_items_state_check"), "grading_job_items", type_="check")
    op.drop_constraint(op.f("grading_job_items_delivery_check"), "grading_job_items", type_="check")
    for column_name in reversed(
        (
            "dispatch_version",
            "retry_count",
            "available_at",
            "lease_token",
            "lease_expires_at",
            "started_at",
            "finished_at",
            "error_code",
            "updated_at",
        )
    ):
        op.drop_column("grading_job_items", column_name)

    op.drop_constraint(
        op.f("grading_jobs_assignment_snapshot_check"), "grading_jobs", type_="check"
    )
    op.drop_constraint(op.f("grading_jobs_progress_check"), "grading_jobs", type_="check")
    op.drop_constraint(op.f("grading_jobs_snapshot_check"), "grading_jobs", type_="check")
    op.create_check_constraint(
        op.f("grading_jobs_snapshot_check"),
        "grading_jobs",
        "provider_config_version > 0 and btrim(model) <> '' "
        "and jsonb_typeof(result_schema) = 'object' "
        "and btrim(prompt_version) <> '' and octet_length(prompt_hash) = 32 "
        "and btrim(result_schema_version) <> '' and octet_length(result_schema_hash) = 32 "
        "and octet_length(rubric_hash) = 32 and btrim(idempotency_key) <> ''",
    )
    for column_name in reversed(
        (
            "assignment_title_snapshot",
            "assignment_instructions_snapshot",
            "expected_item_count",
            "request_hash",
            "model_parameters_hash",
            "state_version",
            "updated_at",
        )
    ):
        op.drop_column("grading_jobs", column_name)

    op.drop_constraint(
        op.f("provider_configs_model_profiles_check"),
        "provider_configs",
        type_="check",
    )
    op.drop_column("provider_configs", "model_profiles")
