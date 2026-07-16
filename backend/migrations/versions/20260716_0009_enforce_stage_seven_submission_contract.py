"""enforce stage seven submission contract

Revision ID: 20260716_0009
Revises: 20260716_0008
Create Date: 2026-07-16 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260716_0009"
down_revision: str | None = "20260716_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSITION_SIGNATURE = "paper_grading_private.transition_submission(uuid, text, text, text)"


def upgrade() -> None:
    """强化论文对象路径和状态约束，并提供最小权限状态转换函数。"""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM public.submissions
                WHERE file_size_bytes <= 0
                   OR file_size_bytes > 20971520
                   OR octet_length(content_sha256) <> 32
                   OR char_length(original_filename) NOT BETWEEN 1 AND 255
                   OR btrim(original_filename) = ''
                   OR source_object_key <> (
                        'teachers/' || owner_id::text ||
                        '/assignments/' || assignment_id::text ||
                        '/submissions/' || id::text ||
                        CASE
                            WHEN media_type = 'application/pdf' THEN '/source.pdf'
                            ELSE '/source.docx'
                        END
                   )
                   OR (
                        extracted_object_key IS NOT NULL
                        AND extracted_object_key <> (
                            'teachers/' || owner_id::text ||
                            '/assignments/' || assignment_id::text ||
                            '/submissions/' || id::text || '/document-blocks.v1.json'
                        )
                   )
                   OR NOT (
                        (status IN ('uploaded', 'parsing')
                            AND extracted_object_key IS NULL AND error_code IS NULL)
                        OR (status = 'ready'
                            AND extracted_object_key IS NOT NULL AND error_code IS NULL)
                        OR (status = 'failed'
                            AND extracted_object_key IS NULL
                            AND error_code IS NOT NULL
                            AND btrim(error_code) <> '')
                   )
            ) THEN
                RAISE EXCEPTION 'invalid existing submission state';
            END IF;
        END;
        $$
        """
    )

    op.drop_constraint(op.f("submissions_ready_check"), "submissions", type_="check")
    op.drop_constraint(op.f("submissions_file_check"), "submissions", type_="check")
    op.create_check_constraint(
        op.f("submissions_file_check"),
        "submissions",
        "file_size_bytes > 0 AND file_size_bytes <= 20971520 "
        "AND octet_length(content_sha256) = 32 "
        "AND btrim(source_object_key) <> ''",
    )
    op.create_check_constraint(
        op.f("submissions_original_filename_check"),
        "submissions",
        "char_length(original_filename) BETWEEN 1 AND 255 AND btrim(original_filename) <> ''",
    )
    op.create_check_constraint(
        op.f("submissions_state_check"),
        "submissions",
        "(status IN ('uploaded', 'parsing') AND extracted_object_key IS NULL "
        "AND error_code IS NULL) OR "
        "(status = 'ready' AND extracted_object_key IS NOT NULL AND error_code IS NULL) OR "
        "(status = 'failed' AND extracted_object_key IS NULL "
        "AND error_code IS NOT NULL AND btrim(error_code) <> '')",
    )
    op.create_check_constraint(
        op.f("submissions_object_keys_check"),
        "submissions",
        "source_object_key = 'teachers/' || owner_id::text || "
        "'/assignments/' || assignment_id::text || '/submissions/' || id::text || "
        "CASE WHEN media_type = 'application/pdf' THEN '/source.pdf' "
        "ELSE '/source.docx' END "
        "AND (extracted_object_key IS NULL OR extracted_object_key = "
        "'teachers/' || owner_id::text || '/assignments/' || assignment_id::text || "
        "'/submissions/' || id::text || '/document-blocks.v1.json')",
    )
    op.create_unique_constraint(
        op.f("submissions_source_object_key_key"),
        "submissions",
        ["source_object_key"],
    )
    op.create_index(
        "submissions_extracted_object_key_idx",
        "submissions",
        ["extracted_object_key"],
        unique=True,
        postgresql_where=sa.text("extracted_object_key IS NOT NULL"),
    )

    op.execute(
        """
        CREATE FUNCTION paper_grading_private.transition_submission(
            target_submission_id uuid,
            target_status text,
            target_extracted_object_key text,
            target_error_code text
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            actor_id uuid;
            current_submission public.submissions%ROWTYPE;
        BEGIN
            actor_id := paper_grading_private.current_active_teacher_id();
            IF actor_id IS NULL THEN
                RAISE EXCEPTION 'active teacher context required'
                    USING ERRCODE = '42501';
            END IF;

            SELECT submission.*
            INTO current_submission
            FROM public.submissions AS submission
            WHERE submission.id = target_submission_id
              AND submission.owner_id = actor_id
            FOR UPDATE;

            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            IF NOT (
                (current_submission.status = 'uploaded' AND target_status = 'parsing'
                    AND target_extracted_object_key IS NULL AND target_error_code IS NULL)
                OR (current_submission.status IN ('uploaded', 'parsing')
                    AND target_status = 'failed'
                    AND target_extracted_object_key IS NULL
                    AND target_error_code IS NOT NULL
                    AND btrim(target_error_code) <> '')
                OR (current_submission.status = 'parsing' AND target_status = 'ready'
                    AND target_extracted_object_key IS NOT NULL
                    AND btrim(target_extracted_object_key) <> ''
                    AND target_error_code IS NULL)
                OR (current_submission.status = 'failed' AND target_status = 'uploaded'
                    AND target_extracted_object_key IS NULL AND target_error_code IS NULL)
            ) THEN
                RAISE EXCEPTION 'invalid submission transition'
                    USING ERRCODE = '55000';
            END IF;

            UPDATE public.submissions
            SET status = target_status,
                extracted_object_key = CASE
                    WHEN target_status = 'ready' THEN target_extracted_object_key
                    ELSE NULL
                END,
                error_code = CASE
                    WHEN target_status = 'failed' THEN target_error_code
                    ELSE NULL
                END
            WHERE id = target_submission_id
              AND owner_id = actor_id;

            RETURN target_submission_id;
        END;
        $$
        """
    )
    op.execute(f"REVOKE EXECUTE ON FUNCTION {TRANSITION_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {TRANSITION_SIGNATURE} TO paper_grading_teacher_api")


def downgrade() -> None:
    """移除阶段七状态函数并恢复阶段二的基础论文约束。"""

    op.execute(f"REVOKE EXECUTE ON FUNCTION {TRANSITION_SIGNATURE} FROM paper_grading_teacher_api")
    op.execute(f"DROP FUNCTION {TRANSITION_SIGNATURE}")
    op.drop_index("submissions_extracted_object_key_idx", table_name="submissions")
    op.drop_constraint(
        op.f("submissions_source_object_key_key"),
        "submissions",
        type_="unique",
    )
    op.drop_constraint(op.f("submissions_object_keys_check"), "submissions", type_="check")
    op.drop_constraint(op.f("submissions_state_check"), "submissions", type_="check")
    op.drop_constraint(
        op.f("submissions_original_filename_check"),
        "submissions",
        type_="check",
    )
    op.drop_constraint(op.f("submissions_file_check"), "submissions", type_="check")
    op.create_check_constraint(
        op.f("submissions_file_check"),
        "submissions",
        "file_size_bytes > 0 AND octet_length(content_sha256) = 32 "
        "AND btrim(source_object_key) <> ''",
    )
    op.create_check_constraint(
        op.f("submissions_ready_check"),
        "submissions",
        "status <> 'ready' OR extracted_object_key IS NOT NULL",
    )
