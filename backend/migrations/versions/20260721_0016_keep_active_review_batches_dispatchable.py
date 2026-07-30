"""教师提前确认时保持未完成评分批次可调度。"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0016"
down_revision: str | None = "20260719_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

API_ROLES = ("PUBLIC", "anon", "authenticated", "service_role")


def upgrade() -> None:
    """阻止部分确认把仍有排队或运行论文的批次提前收口。"""

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_preserve_active_job_status()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF NEW.status = 'needs_review'
               AND EXISTS (
                   SELECT 1
                   FROM public.grading_job_items AS item
                   WHERE item.grading_job_id = NEW.id
                     AND item.owner_id = NEW.owner_id
                     AND item.status IN ('queued', 'running')
               ) THEN
                IF OLD.status = 'paused' THEN
                    NEW.status := 'paused';
                ELSE
                    NEW.status := 'running';
                    NEW.started_at := COALESCE(NEW.started_at, transaction_timestamp());
                END IF;
                NEW.finished_at := NULL;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for role in API_ROLES:
        op.execute(
            "REVOKE EXECUTE ON FUNCTION "
            f"public.paper_grading_preserve_active_job_status() FROM {role}"
        )
    op.execute(
        """
        CREATE TRIGGER grading_jobs_preserve_active_status
        BEFORE UPDATE OF status ON public.grading_jobs
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_preserve_active_job_status()
        """
    )
    op.execute(
        """
        UPDATE public.grading_jobs AS job
        SET status = 'running',
            started_at = COALESCE(job.started_at, transaction_timestamp()),
            finished_at = NULL,
            state_version = job.state_version + 1,
            updated_at = transaction_timestamp()
        WHERE job.status = 'needs_review'
          AND EXISTS (
              SELECT 1
              FROM public.grading_job_items AS item
              WHERE item.grading_job_id = job.id
                AND item.owner_id = job.owner_id
                AND item.status IN ('queued', 'running')
          )
        """
    )


def downgrade() -> None:
    """移除主动批次状态保护；不回写已经修复的业务状态。"""

    op.execute("DROP TRIGGER grading_jobs_preserve_active_status ON public.grading_jobs")
    op.execute("DROP FUNCTION public.paper_grading_preserve_active_job_status()")
