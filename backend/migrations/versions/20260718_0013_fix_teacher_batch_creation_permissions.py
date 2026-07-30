"""修复教师创建评分批次时不必要的行锁权限冲突。

Revision ID: 20260718_0013
Revises: 20260716_0012
Create Date: 2026-07-18
"""

from alembic import op

revision = "20260718_0013"
down_revision = "20260716_0012"
branch_labels = None
depends_on = None


def _replace_ready_job_item_guard(*, lock_rows: bool) -> None:
    job_lock = "\n            FOR UPDATE" if lock_rows else ""
    submission_lock = "\n            FOR SHARE" if lock_rows else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_require_ready_job_item()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = ''
        AS $$
        DECLARE
            target_job_status text;
            target_expected_count integer;
            target_submission_status text;
        BEGIN
            SELECT status, expected_item_count
            INTO target_job_status, target_expected_count
            FROM public.grading_jobs
            WHERE id = NEW.grading_job_id
              AND assignment_id = NEW.assignment_id
              AND owner_id = NEW.owner_id{job_lock};
            IF NOT FOUND OR target_job_status <> 'queued' THEN
                RAISE EXCEPTION 'grading job item requires a queued job'
                    USING ERRCODE = '23514';
            END IF;

            SELECT status INTO target_submission_status
            FROM public.submissions
            WHERE id = NEW.submission_id
              AND assignment_id = NEW.assignment_id
              AND owner_id = NEW.owner_id{submission_lock};
            IF NOT FOUND OR target_submission_status <> 'ready' THEN
                RAISE EXCEPTION 'grading job item requires a ready submission'
                    USING ERRCODE = '23514';
            END IF;

            IF NEW.position >= target_expected_count THEN
                RAISE EXCEPTION 'grading job item position exceeds expected count'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    """保留教师最小权限，移除只读校验中的多余行锁。"""

    _replace_ready_job_item_guard(lock_rows=False)


def downgrade() -> None:
    """恢复阶段十初版的行锁行为。"""

    _replace_ready_job_item_guard(lock_rows=True)
