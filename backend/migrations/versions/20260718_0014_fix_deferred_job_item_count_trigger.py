"""修复延迟批次完整性触发器访问错误的记录字段。

Revision ID: 20260718_0014
Revises: 20260718_0013
Create Date: 2026-07-18
"""

from alembic import op

revision = "20260718_0014"
down_revision = "20260718_0013"
branch_labels = None
depends_on = None


def _replace_job_item_count_guard(*, separate_record_types: bool) -> None:
    target_assignment = (
        """
            IF TG_TABLE_NAME = 'grading_jobs' THEN
                target_job_id := NEW.id;
            ELSIF TG_TABLE_NAME = 'grading_job_items' THEN
                target_job_id := NEW.grading_job_id;
            ELSE
                RAISE EXCEPTION 'unsupported grading item count trigger table'
                    USING ERRCODE = '55000';
            END IF;"""
        if separate_record_types
        else """
            target_job_id := CASE
                WHEN TG_TABLE_NAME = 'grading_jobs' THEN NEW.id
                ELSE NEW.grading_job_id
            END;"""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_validate_job_item_count()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = ''
        AS $$
        DECLARE
            target_job_id uuid;
            expected_count integer;
            actual_count integer;
        BEGIN{target_assignment}
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


def upgrade() -> None:
    """按触发表分别访问各自存在的 NEW 字段。"""

    _replace_job_item_count_guard(separate_record_types=True)


def downgrade() -> None:
    """恢复阶段十初版的单 CASE 表达式。"""

    _replace_job_item_count_guard(separate_record_types=False)
