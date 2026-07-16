"""收紧阶段 2 数据库函数边界并补齐评分记录初始状态。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260714_0003"
down_revision: str | None = "20260713_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXISTING_STAGE_TWO_FUNCTIONS = (
    "paper_grading_set_updated_at",
    "paper_grading_protect_rubric_history",
    "paper_grading_protect_job_snapshot",
    "paper_grading_reject_history_mutation",
    "paper_grading_protect_attempt_history",
    "paper_grading_validate_attempt_score",
    "paper_grading_protect_review_history",
    "paper_grading_validate_review_score",
)
REQUIRE_RUNNING_FUNCTION = "paper_grading_require_running_attempt_insert"
STAGE_TWO_INTERNAL_FUNCTIONS = (
    *EXISTING_STAGE_TWO_FUNCTIONS,
    REQUIRE_RUNNING_FUNCTION,
)
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")


def upgrade() -> None:
    """让已部署和全新数据库收敛到同一个阶段 2 安全状态。"""

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.paper_grading_require_running_attempt_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF NEW.status <> 'running' THEN
                RAISE EXCEPTION 'grading attempt must start in running status'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS grading_attempts_require_running_insert
        ON public.grading_attempts
        """
    )
    op.execute(
        """
        CREATE TRIGGER grading_attempts_require_running_insert
        BEFORE INSERT ON public.grading_attempts
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_require_running_attempt_insert()
        """
    )

    for function_name in EXISTING_STAGE_TWO_FUNCTIONS:
        op.execute(f"ALTER FUNCTION public.{function_name}() SET search_path = ''")

    for function_name in STAGE_TWO_INTERNAL_FUNCTIONS:
        op.execute(f"REVOKE EXECUTE ON FUNCTION public.{function_name}() FROM PUBLIC")

    function_names = ", ".join(f"'{name}'" for name in STAGE_TWO_INTERNAL_FUNCTIONS)
    api_roles = ", ".join(f"'{role}'" for role in SUPABASE_API_ROLES)
    op.execute(
        f"""
        DO $paper_grading$
        DECLARE
            target_function text;
            target_role text;
        BEGIN
            FOREACH target_function IN ARRAY ARRAY[{function_names}]
            LOOP
                FOR target_role IN
                    SELECT rolname
                    FROM pg_catalog.pg_roles
                    WHERE rolname IN ({api_roles})
                LOOP
                    EXECUTE pg_catalog.format(
                        'REVOKE EXECUTE ON FUNCTION public.%I() FROM %I',
                        target_function,
                        target_role
                    );
                END LOOP;
            END LOOP;

            IF pg_catalog.to_regprocedure('public.rls_auto_enable()') IS NOT NULL THEN
                EXECUTE
                    'REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC';
                FOR target_role IN
                    SELECT rolname
                    FROM pg_catalog.pg_roles
                    WHERE rolname IN ({api_roles})
                LOOP
                    EXECUTE pg_catalog.format(
                        'REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM %I',
                        target_role
                    );
                END LOOP;
            END IF;
        END;
        $paper_grading$
        """
    )


def downgrade() -> None:
    """恢复到已发布的阶段 2 基线，不恢复外部函数的不安全公开权限。"""

    op.execute(
        """
        DROP TRIGGER IF EXISTS grading_attempts_require_running_insert
        ON public.grading_attempts
        """
    )
    op.execute("DROP FUNCTION IF EXISTS public.paper_grading_require_running_attempt_insert()")

    for function_name in EXISTING_STAGE_TWO_FUNCTIONS:
        op.execute(f"ALTER FUNCTION public.{function_name}() RESET search_path")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{function_name}() TO PUBLIC")
