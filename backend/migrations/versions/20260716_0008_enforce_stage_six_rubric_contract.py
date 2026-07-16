"""enforce stage six rubric contract

Revision ID: 20260716_0008
Revises: 20260715_0007
Create Date: 2026-07-16 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0008"
down_revision: str | None = "20260715_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEACHER_ROLE = "paper_grading_teacher_api"
API_ROLES = ("anon", "authenticated", "service_role")


def _revoke_execute_if_role_exists(function_signature: str, role_name: str) -> None:
    """对固定角色撤销函数权限，不在匿名代码块内使用绑定参数。"""

    if role_name not in API_ROLES:
        raise ValueError("不允许迁移未知数据库角色")
    revoke_statement = f"REVOKE EXECUTE ON FUNCTION public.{function_signature} FROM {role_name}"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_name}') THEN
                EXECUTE '{revoke_statement}';
            END IF;
        END;
        $$
        """
    )


def upgrade() -> None:
    """增加阶段六需要的 Rubric 结构、版本和批改入口约束。"""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM public.assignments WHERE btrim(instructions) = ''
            ) THEN
                RAISE EXCEPTION 'blank assignment instructions exist';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM public.rubric_versions
                WHERE status IN ('confirmed', 'superseded')
            ) THEN
                RAISE EXCEPTION 'existing confirmed rubric requires an explicit migration plan';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM public.rubric_versions
                WHERE status IN ('draft', 'confirmed')
                GROUP BY assignment_id, status
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'duplicate current rubric version exists';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM public.assignments AS assignment
                WHERE assignment.status = 'ready'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM public.rubric_versions AS rubric
                      WHERE rubric.assignment_id = assignment.id
                        AND rubric.owner_id = assignment.owner_id
                        AND rubric.status = 'confirmed'
                  )
            ) THEN
                RAISE EXCEPTION 'ready assignment without confirmed rubric exists';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM public.grading_jobs AS job
                JOIN public.rubric_versions AS rubric
                  ON rubric.id = job.rubric_version_id
                 AND rubric.assignment_id = job.assignment_id
                 AND rubric.owner_id = job.owner_id
                WHERE rubric.status <> 'confirmed'
            ) THEN
                RAISE EXCEPTION 'grading job with unconfirmed rubric exists';
            END IF;
        END;
        $$
        """
    )

    op.add_column("rubric_versions", sa.Column("provider_config_id", sa.Uuid(), nullable=True))
    op.add_column("rubric_versions", sa.Column("model", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("rubric_versions_provider_config_id_fkey"),
        "rubric_versions",
        "provider_configs",
        ["provider_config_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "rubric_versions_provider_config_id_idx",
        "rubric_versions",
        ["provider_config_id"],
        unique=False,
    )
    op.create_index(
        "rubric_versions_one_draft_idx",
        "rubric_versions",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "rubric_versions_one_confirmed_idx",
        "rubric_versions",
        ["assignment_id"],
        unique=True,
        postgresql_where=sa.text("status = 'confirmed'"),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.paper_grading_protect_rubric_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'rubric version history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                NEW.id,
                NEW.owner_id,
                NEW.assignment_id,
                NEW.version,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.assignment_id,
                OLD.version,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'rubric version identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'superseded' THEN
                RAISE EXCEPTION 'superseded rubric version is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'confirmed' THEN
                IF NEW.status <> 'superseded' OR ROW(
                    NEW.original_rubric,
                    NEW.structured_rubric,
                    NEW.total_score,
                    NEW.score_step,
                    NEW.provider_config_id,
                    NEW.model,
                    NEW.confirmed_at
                ) IS DISTINCT FROM ROW(
                    OLD.original_rubric,
                    OLD.structured_rubric,
                    OLD.total_score,
                    OLD.score_step,
                    OLD.provider_config_id,
                    OLD.model,
                    OLD.confirmed_at
                ) THEN
                    RAISE EXCEPTION 'confirmed rubric content is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM public.assignments AS assignment
                    WHERE assignment.id = OLD.assignment_id
                      AND assignment.owner_id = OLD.owner_id
                      AND assignment.status = 'ready'
                ) THEN
                    RAISE EXCEPTION 'ready assignment cannot lose its confirmed rubric'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.status NOT IN ('draft', 'confirmed') THEN
                RAISE EXCEPTION 'draft rubric can only remain draft or become confirmed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_valid_structured_rubric(
            payload jsonb,
            expected_total numeric,
            expected_step numeric
        )
        RETURNS boolean
        LANGUAGE plpgsql
        IMMUTABLE
        SET search_path = ''
        AS $$
        DECLARE
            dimension jsonb;
            dimension_id text;
            dimension_name text;
            dimension_max numeric;
            dimension_total numeric := 0;
            dimension_ids text[] := ARRAY[]::text[];
            dimension_names text[] := ARRAY[]::text[];
            band jsonb;
            band_min numeric;
            band_max numeric;
            previous_band_max numeric;
            requirement jsonb;
            deduction jsonb;
            deduction_points numeric;
        BEGIN
            IF payload IS NULL
                OR jsonb_typeof(payload) <> 'object'
                OR NOT (payload ?& ARRAY[
                    'schema_version', 'total_score', 'score_step', 'dimensions', 'deductions'
                ])
                OR payload - ARRAY[
                    'schema_version', 'total_score', 'score_step', 'dimensions', 'deductions'
                ] <> '{}'::jsonb
                OR jsonb_typeof(payload -> 'schema_version') <> 'number'
                OR payload ->> 'schema_version' <> '1'
                OR jsonb_typeof(payload -> 'total_score') <> 'string'
                OR jsonb_typeof(payload -> 'score_step') <> 'string'
                OR (payload ->> 'total_score')::numeric <> expected_total
                OR (payload ->> 'score_step')::numeric <> expected_step
                OR expected_total <= 0
                OR expected_step <= 0
                OR expected_step > expected_total
                OR mod(expected_total, expected_step) <> 0
                OR jsonb_typeof(payload -> 'dimensions') <> 'array'
                OR jsonb_array_length(payload -> 'dimensions') = 0
                OR jsonb_typeof(payload -> 'deductions') <> 'array'
            THEN
                RETURN FALSE;
            END IF;

            FOR dimension IN
                SELECT value FROM jsonb_array_elements(payload -> 'dimensions')
            LOOP
                IF jsonb_typeof(dimension) <> 'object'
                    OR NOT (dimension ?& ARRAY[
                        'id', 'name', 'description', 'max_score', 'bands',
                        'evidence_requirements'
                    ])
                    OR dimension - ARRAY[
                        'id', 'name', 'description', 'max_score', 'bands',
                        'evidence_requirements'
                    ] <> '{}'::jsonb
                    OR jsonb_typeof(dimension -> 'id') <> 'string'
                    OR jsonb_typeof(dimension -> 'name') <> 'string'
                    OR jsonb_typeof(dimension -> 'description') <> 'string'
                    OR jsonb_typeof(dimension -> 'max_score') <> 'string'
                    OR jsonb_typeof(dimension -> 'bands') <> 'array'
                    OR jsonb_array_length(dimension -> 'bands') = 0
                    OR jsonb_typeof(dimension -> 'evidence_requirements') <> 'array'
                    OR jsonb_array_length(dimension -> 'evidence_requirements') = 0
                THEN
                    RETURN FALSE;
                END IF;

                dimension_id := dimension ->> 'id';
                dimension_name := lower(
                    regexp_replace(btrim(dimension ->> 'name'), '[[:space:]]+', ' ', 'g')
                );
                dimension_max := (dimension ->> 'max_score')::numeric;
                IF dimension_id !~ '^[a-z][a-z0-9_]{0,63}$'
                    OR dimension_id = ANY(dimension_ids)
                    OR dimension_name = ''
                    OR dimension_name = ANY(dimension_names)
                    OR btrim(dimension ->> 'description') = ''
                    OR dimension_max <= 0
                    OR mod(dimension_max, expected_step) <> 0
                THEN
                    RETURN FALSE;
                END IF;
                dimension_ids := array_append(dimension_ids, dimension_id);
                dimension_names := array_append(dimension_names, dimension_name);
                dimension_total := dimension_total + dimension_max;

                previous_band_max := NULL;
                FOR band IN
                    SELECT value FROM jsonb_array_elements(dimension -> 'bands')
                LOOP
                    IF jsonb_typeof(band) <> 'object'
                        OR NOT (band ?& ARRAY[
                            'label', 'min_score', 'max_score', 'description'
                        ])
                        OR band - ARRAY[
                            'label', 'min_score', 'max_score', 'description'
                        ] <> '{}'::jsonb
                        OR jsonb_typeof(band -> 'label') <> 'string'
                        OR jsonb_typeof(band -> 'min_score') <> 'string'
                        OR jsonb_typeof(band -> 'max_score') <> 'string'
                        OR jsonb_typeof(band -> 'description') <> 'string'
                        OR btrim(band ->> 'label') = ''
                        OR btrim(band ->> 'description') = ''
                    THEN
                        RETURN FALSE;
                    END IF;
                    band_min := (band ->> 'min_score')::numeric;
                    band_max := (band ->> 'max_score')::numeric;
                    IF band_min < 0
                        OR band_min > band_max
                        OR band_max > dimension_max
                        OR mod(band_min, expected_step) <> 0
                        OR mod(band_max, expected_step) <> 0
                        OR (
                            previous_band_max IS NULL AND band_min <> 0
                        )
                        OR (
                            previous_band_max IS NOT NULL
                            AND band_min <> previous_band_max + expected_step
                        )
                    THEN
                        RETURN FALSE;
                    END IF;
                    previous_band_max := band_max;
                END LOOP;
                IF previous_band_max <> dimension_max THEN
                    RETURN FALSE;
                END IF;

                FOR requirement IN
                    SELECT value
                    FROM jsonb_array_elements(dimension -> 'evidence_requirements')
                LOOP
                    IF jsonb_typeof(requirement) <> 'string'
                        OR btrim(requirement #>> '{}') = ''
                    THEN
                        RETURN FALSE;
                    END IF;
                END LOOP;
            END LOOP;

            IF dimension_total <> expected_total THEN
                RETURN FALSE;
            END IF;

            FOR deduction IN
                SELECT value FROM jsonb_array_elements(payload -> 'deductions')
            LOOP
                IF jsonb_typeof(deduction) <> 'object'
                    OR NOT (deduction ?& ARRAY[
                        'id', 'name', 'description', 'points'
                    ])
                    OR deduction - ARRAY[
                        'id', 'name', 'description', 'points'
                    ] <> '{}'::jsonb
                    OR jsonb_typeof(deduction -> 'id') <> 'string'
                    OR jsonb_typeof(deduction -> 'name') <> 'string'
                    OR jsonb_typeof(deduction -> 'description') <> 'string'
                    OR jsonb_typeof(deduction -> 'points') <> 'string'
                    OR (deduction ->> 'id') !~ '^[a-z][a-z0-9_]{0,63}$'
                    OR btrim(deduction ->> 'name') = ''
                    OR btrim(deduction ->> 'description') = ''
                THEN
                    RETURN FALSE;
                END IF;
                deduction_points := (deduction ->> 'points')::numeric;
                IF deduction_points <= 0
                    OR deduction_points > expected_total
                    OR mod(deduction_points, expected_step) <> 0
                THEN
                    RETURN FALSE;
                END IF;
            END LOOP;

            RETURN TRUE;
        EXCEPTION
            WHEN OTHERS THEN
                RETURN FALSE;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "public.paper_grading_valid_structured_rubric(jsonb, numeric, numeric) FROM PUBLIC"
    )
    for role_name in API_ROLES:
        _revoke_execute_if_role_exists(
            "paper_grading_valid_structured_rubric(jsonb, numeric, numeric)",
            role_name,
        )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"public.paper_grading_valid_structured_rubric(jsonb, numeric, numeric) "
        f"TO {TEACHER_ROLE}"
    )

    op.create_check_constraint(
        op.f("assignments_instructions_check"),
        "assignments",
        "btrim(instructions) <> ''",
    )
    op.create_check_constraint(
        op.f("rubric_versions_generation_check"),
        "rubric_versions",
        "((provider_config_id is null and model is null) or "
        "(provider_config_id is not null and btrim(model) <> '')) "
        "and (structured_rubric is null or provider_config_id is not null)",
    )
    op.create_check_constraint(
        op.f("rubric_versions_content_check"),
        "rubric_versions",
        "structured_rubric is null or "
        "public.paper_grading_valid_structured_rubric("
        "structured_rubric, total_score, score_step)",
    )
    op.drop_constraint(
        op.f("rubric_versions_confirmation_check"),
        "rubric_versions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("rubric_versions_confirmation_check"),
        "rubric_versions",
        "(status = 'draft' and confirmed_at is null) or "
        "(status in ('confirmed', 'superseded') and confirmed_at is not null "
        "and structured_rubric is not null and provider_config_id is not null "
        "and btrim(model) <> '')",
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_require_confirmed_rubric_for_ready_assignment()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF NEW.status = 'ready'
                AND NOT EXISTS (
                    SELECT 1
                    FROM public.rubric_versions AS rubric
                    WHERE rubric.assignment_id = NEW.id
                      AND rubric.owner_id = NEW.owner_id
                      AND rubric.status = 'confirmed'
                )
            THEN
                RAISE EXCEPTION 'ready assignment requires a confirmed rubric'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER assignments_require_confirmed_rubric
        BEFORE INSERT OR UPDATE OF status ON public.assignments
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_require_confirmed_rubric_for_ready_assignment()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.paper_grading_require_confirmed_job_rubric()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM public.rubric_versions AS rubric
                JOIN public.assignments AS assignment
                  ON assignment.id = rubric.assignment_id
                 AND assignment.owner_id = rubric.owner_id
                WHERE rubric.id = NEW.rubric_version_id
                  AND rubric.assignment_id = NEW.assignment_id
                  AND rubric.owner_id = NEW.owner_id
                  AND rubric.status = 'confirmed'
                  AND assignment.status = 'ready'
            )
            THEN
                RAISE EXCEPTION 'grading job requires a confirmed rubric and ready assignment'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER grading_jobs_require_confirmed_rubric
        BEFORE INSERT ON public.grading_jobs
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_require_confirmed_job_rubric()
        """
    )
    for function_signature in (
        "paper_grading_require_confirmed_rubric_for_ready_assignment()",
        "paper_grading_require_confirmed_job_rubric()",
    ):
        op.execute(f"REVOKE EXECUTE ON FUNCTION public.{function_signature} FROM PUBLIC")
        for role_name in API_ROLES:
            _revoke_execute_if_role_exists(function_signature, role_name)


def downgrade() -> None:
    """移除阶段六门禁并恢复阶段五结构。"""

    op.execute("DROP TRIGGER grading_jobs_require_confirmed_rubric ON public.grading_jobs")
    op.execute("DROP FUNCTION public.paper_grading_require_confirmed_job_rubric()")
    op.execute("DROP TRIGGER assignments_require_confirmed_rubric ON public.assignments")
    op.execute("DROP FUNCTION public.paper_grading_require_confirmed_rubric_for_ready_assignment()")

    op.drop_constraint(
        op.f("rubric_versions_confirmation_check"),
        "rubric_versions",
        type_="check",
    )
    op.create_check_constraint(
        op.f("rubric_versions_confirmation_check"),
        "rubric_versions",
        "(status = 'draft' and confirmed_at is null) or "
        "(status in ('confirmed', 'superseded') and confirmed_at is not null "
        "and structured_rubric is not null)",
    )
    op.drop_constraint(
        op.f("rubric_versions_content_check"),
        "rubric_versions",
        type_="check",
    )
    op.drop_constraint(
        op.f("rubric_versions_generation_check"),
        "rubric_versions",
        type_="check",
    )
    op.drop_constraint(
        op.f("assignments_instructions_check"),
        "assignments",
        type_="check",
    )
    op.execute(
        "DROP FUNCTION public.paper_grading_valid_structured_rubric(jsonb, numeric, numeric)"
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.paper_grading_protect_rubric_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'rubric version history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                NEW.id,
                NEW.owner_id,
                NEW.assignment_id,
                NEW.version,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.assignment_id,
                OLD.version,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'rubric version identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'superseded' THEN
                RAISE EXCEPTION 'superseded rubric version is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'confirmed' THEN
                IF NEW.status <> 'superseded' OR ROW(
                    NEW.original_rubric,
                    NEW.structured_rubric,
                    NEW.total_score,
                    NEW.score_step,
                    NEW.confirmed_at
                ) IS DISTINCT FROM ROW(
                    OLD.original_rubric,
                    OLD.structured_rubric,
                    OLD.total_score,
                    OLD.score_step,
                    OLD.confirmed_at
                ) THEN
                    RAISE EXCEPTION 'confirmed rubric content is immutable'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.status NOT IN ('draft', 'confirmed') THEN
                RAISE EXCEPTION 'draft rubric can only remain draft or become confirmed'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )

    op.drop_index("rubric_versions_one_confirmed_idx", table_name="rubric_versions")
    op.drop_index("rubric_versions_one_draft_idx", table_name="rubric_versions")
    op.drop_index("rubric_versions_provider_config_id_idx", table_name="rubric_versions")
    op.drop_constraint(
        op.f("rubric_versions_provider_config_id_fkey"),
        "rubric_versions",
        type_="foreignkey",
    )
    op.drop_column("rubric_versions", "model")
    op.drop_column("rubric_versions", "provider_config_id")
