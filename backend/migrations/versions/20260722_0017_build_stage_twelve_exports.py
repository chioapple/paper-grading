"""建立阶段十二不可变 Excel 导出快照与独立 Worker 状态机。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260722_0017"
down_revision: str | None = "20260721_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEACHER_ROLE = "paper_grading_teacher_api"
EXPORT_WORKER_ROLE = "paper_grading_export_worker"
API_ROLES = ("PUBLIC", "anon", "authenticated", "service_role")


def _revoke_execute(signature: str) -> None:
    for role in API_ROLES:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {role}")


def _create_export_protection() -> None:
    op.execute(
        """
        CREATE FUNCTION public.paper_grading_protect_export_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'export history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(
                NEW.id, NEW.owner_id, NEW.assignment_id, NEW.grading_job_id,
                NEW.export_type, NEW.audit_metadata, NEW.idempotency_key,
                NEW.request_hash, NEW.workbook_schema_version, NEW.snapshot_at,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.owner_id, OLD.assignment_id, OLD.grading_job_id,
                OLD.export_type, OLD.audit_metadata, OLD.idempotency_key,
                OLD.request_hash, OLD.workbook_schema_version, OLD.snapshot_at,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'export snapshot is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT (
                (OLD.status = 'queued' AND NEW.status = 'running')
                OR (OLD.status = 'running' AND NEW.status IN ('completed', 'failed'))
                OR (
                    OLD.status = 'running' AND NEW.status = 'running'
                    AND OLD.lease_expires_at <= transaction_timestamp()
                    AND NEW.claim_token IS DISTINCT FROM OLD.claim_token
                )
            ) THEN
                RAISE EXCEPTION 'invalid export status transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_protect_export_history()")
    op.execute(
        """
        CREATE TRIGGER exports_protect_history
        BEFORE UPDATE OR DELETE ON public.exports
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_protect_export_history()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.paper_grading_reject_export_item_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            RAISE EXCEPTION 'export item snapshot is immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_reject_export_item_mutation()")
    op.execute(
        """
        CREATE TRIGGER export_items_reject_mutation
        BEFORE UPDATE OR DELETE ON public.export_items
        FOR EACH ROW EXECUTE FUNCTION public.paper_grading_reject_export_item_mutation()
        """
    )


def _create_teacher_function() -> None:
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.create_export(
            p_grading_job_id uuid,
            p_export_type text,
            p_idempotency_key text,
            p_request_hash bytea
        )
        RETURNS public.exports
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            teacher_id uuid;
            current_job public.grading_jobs%ROWTYPE;
            current_rubric public.rubric_versions%ROWTYPE;
            existing_export public.exports%ROWTYPE;
            created_export public.exports%ROWTYPE;
            item_row public.grading_job_items%ROWTYPE;
            attempt_row public.grading_attempts%ROWTYPE;
            review_row public.teacher_reviews%ROWTYPE;
            submission_row public.submissions%ROWTYPE;
            source_value text;
            frozen_result jsonb;
            actual_item_count integer;
            frozen_item_count integer := 0;
        BEGIN
            teacher_id := paper_grading_private.current_active_teacher_id();
            IF teacher_id IS NULL THEN
                RAISE EXCEPTION 'export_job_not_found' USING ERRCODE = 'P0001';
            END IF;
            IF p_export_type NOT IN ('draft', 'final')
               OR p_idempotency_key IS NULL OR btrim(p_idempotency_key) = ''
               OR char_length(p_idempotency_key) > 200
               OR octet_length(p_request_hash) <> 32 THEN
                RAISE EXCEPTION 'export_snapshot_invalid' USING ERRCODE = 'P0001';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(teacher_id::text || ':' || p_idempotency_key, 0)
            );
            SELECT * INTO existing_export
            FROM public.exports
            WHERE owner_id = teacher_id AND idempotency_key = p_idempotency_key
            FOR UPDATE;
            IF FOUND THEN
                IF existing_export.request_hash <> p_request_hash
                   OR existing_export.grading_job_id <> p_grading_job_id
                   OR existing_export.export_type <> p_export_type THEN
                    RAISE EXCEPTION 'export_idempotency_conflict' USING ERRCODE = 'P0001';
                END IF;
                RETURN existing_export;
            END IF;

            SELECT * INTO current_job
            FROM public.grading_jobs
            WHERE id = p_grading_job_id AND owner_id = teacher_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'export_job_not_found' USING ERRCODE = 'P0001';
            END IF;
            IF (p_export_type = 'final' AND current_job.status <> 'completed')
               OR (
                   p_export_type = 'draft'
                   AND current_job.status NOT IN ('needs_review', 'completed')
               ) THEN
                RAISE EXCEPTION 'export_job_not_ready' USING ERRCODE = 'P0001';
            END IF;

            PERFORM 1
            FROM public.grading_job_items AS item
            WHERE item.grading_job_id = current_job.id
              AND item.owner_id = teacher_id
            ORDER BY item.id
            FOR UPDATE;
            SELECT count(*) INTO actual_item_count
            FROM public.grading_job_items AS item
            WHERE item.grading_job_id = current_job.id
              AND item.owner_id = teacher_id;
            IF actual_item_count <> current_job.expected_item_count
               OR actual_item_count NOT BETWEEN 1 AND 100
               OR EXISTS (
                   SELECT 1 FROM public.grading_job_items AS item
                   WHERE item.grading_job_id = current_job.id
                     AND item.owner_id = teacher_id
                     AND item.status NOT IN ('needs_review', 'completed')
               )
               OR (SELECT min(position) FROM public.grading_job_items
                   WHERE grading_job_id = current_job.id AND owner_id = teacher_id) <> 0
               OR (SELECT max(position) FROM public.grading_job_items
                   WHERE grading_job_id = current_job.id AND owner_id = teacher_id)
                  <> actual_item_count - 1 THEN
                RAISE EXCEPTION 'export_job_not_ready' USING ERRCODE = 'P0001';
            END IF;

            PERFORM 1
            FROM public.grading_attempts AS attempt
            JOIN public.grading_job_items AS item
              ON item.id = attempt.grading_job_item_id
             AND item.owner_id = attempt.owner_id
            WHERE item.grading_job_id = current_job.id
              AND item.owner_id = teacher_id
              AND attempt.scoring_round = item.dispatch_version
              AND attempt.status = 'succeeded'
            ORDER BY attempt.id
            FOR UPDATE OF attempt;
            PERFORM 1
            FROM public.teacher_reviews AS review
            JOIN public.grading_job_items AS item
              ON item.id = review.grading_job_item_id
             AND item.owner_id = review.owner_id
            WHERE item.grading_job_id = current_job.id
              AND item.owner_id = teacher_id
            ORDER BY review.id
            FOR UPDATE OF review;

            SELECT * INTO current_rubric
            FROM public.rubric_versions
            WHERE id = current_job.rubric_version_id
              AND assignment_id = current_job.assignment_id
              AND owner_id = teacher_id
            FOR SHARE;
            IF NOT FOUND OR current_rubric.status NOT IN ('confirmed', 'superseded')
               OR current_rubric.structured_rubric IS NULL
               OR current_rubric.total_score <= 0
               OR current_job.rubric_hash IS NULL
               OR octet_length(current_job.rubric_hash) <> 32 THEN
                RAISE EXCEPTION 'export_snapshot_invalid' USING ERRCODE = 'P0001';
            END IF;

            INSERT INTO public.exports(
                owner_id, assignment_id, grading_job_id, export_type, status,
                audit_metadata, idempotency_key, request_hash,
                workbook_schema_version, snapshot_at
            ) VALUES (
                teacher_id, current_job.assignment_id, current_job.id, p_export_type, 'queued',
                jsonb_build_object(
                    'schema_version', 'export-batch-snapshot.v1',
                    'assignment_title', current_job.assignment_title_snapshot,
                    'rubric_version_id', current_rubric.id,
                    'rubric_version', current_rubric.version,
                    'rubric', current_rubric.structured_rubric,
                    'provider_config_id', current_job.provider_config_id,
                    'provider_config_version', current_job.provider_config_version,
                    'model', current_job.model,
                    'model_parameters', current_job.model_parameters,
                    'model_parameters_hash', encode(current_job.model_parameters_hash, 'hex'),
                    'prompt_version', current_job.prompt_version,
                    'prompt_hash', encode(current_job.prompt_hash, 'hex'),
                    'result_schema_version', current_job.result_schema_version,
                    'result_schema_hash', encode(current_job.result_schema_hash, 'hex'),
                    'rubric_hash', encode(current_job.rubric_hash, 'hex'),
                    'paper_count', current_job.expected_item_count
                ),
                p_idempotency_key, p_request_hash,
                'paper-grading-workbook.v1', transaction_timestamp()
            )
            RETURNING * INTO created_export;

            FOR item_row IN
                SELECT * FROM public.grading_job_items
                WHERE grading_job_id = current_job.id AND owner_id = teacher_id
                ORDER BY position
            LOOP
                SELECT * INTO submission_row
                FROM public.submissions
                WHERE id = item_row.submission_id
                  AND assignment_id = current_job.assignment_id
                  AND owner_id = teacher_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'export_snapshot_invalid' USING ERRCODE = 'P0001';
                END IF;
                SELECT * INTO attempt_row
                FROM public.grading_attempts
                WHERE grading_job_item_id = item_row.id
                  AND owner_id = teacher_id
                  AND scoring_round = item_row.dispatch_version
                  AND status = 'succeeded'
                ORDER BY attempt_number DESC
                LIMIT 1;
                IF NOT FOUND OR attempt_row.criteria_results IS NULL
                   OR attempt_row.deduction_results IS NULL
                   OR attempt_row.overall_feedback IS NULL
                   OR attempt_row.subtotal IS NULL
                   OR attempt_row.deduction_total IS NULL
                   OR attempt_row.total_score IS NULL
                   OR attempt_row.max_score <> current_rubric.total_score
                   OR attempt_row.total_score <> greatest(
                       0::numeric, attempt_row.subtotal - attempt_row.deduction_total
                   ) THEN
                    RAISE EXCEPTION 'export_source_missing' USING ERRCODE = 'P0001';
                END IF;

                SELECT * INTO review_row
                FROM public.teacher_reviews
                WHERE grading_attempt_id = attempt_row.id
                  AND grading_job_item_id = item_row.id
                  AND owner_id = teacher_id;
                IF FOUND AND review_row.status = 'confirmed' THEN
                    source_value := 'teacher_confirmed';
                ELSIF p_export_type = 'final' THEN
                    RAISE EXCEPTION 'export_final_unconfirmed' USING ERRCODE = 'P0001';
                ELSIF FOUND AND review_row.status = 'draft' THEN
                    source_value := 'teacher_draft';
                ELSE
                    source_value := 'ai_suggestion';
                END IF;
                IF p_export_type = 'final' AND item_row.status <> 'completed' THEN
                    RAISE EXCEPTION 'export_final_unconfirmed' USING ERRCODE = 'P0001';
                END IF;
                IF item_row.status = 'completed' AND source_value <> 'teacher_confirmed' THEN
                    RAISE EXCEPTION 'export_snapshot_invalid' USING ERRCODE = 'P0001';
                END IF;

                IF source_value = 'ai_suggestion' THEN
                    frozen_result := jsonb_build_object(
                        'schema_version', 'export-item-snapshot.v1',
                        'item_status', item_row.status,
                        'max_score', attempt_row.max_score,
                        'subtotal', attempt_row.subtotal,
                        'deduction_total', attempt_row.deduction_total,
                        'final_score', attempt_row.total_score,
                        'criteria_results', attempt_row.criteria_results,
                        'deduction_results', attempt_row.deduction_results,
                        'evidence', '[]'::jsonb,
                        'overall_feedback', attempt_row.overall_feedback,
                        'change_reason', NULL,
                        'confirmed_at', NULL,
                        'attempt_number', attempt_row.attempt_number,
                        'scoring_round', attempt_row.scoring_round
                    );
                ELSE
                    IF review_row.max_score <> current_rubric.total_score
                       OR review_row.final_score <> greatest(
                           0::numeric, review_row.subtotal - review_row.deduction_total
                       ) THEN
                        RAISE EXCEPTION 'export_snapshot_invalid' USING ERRCODE = 'P0001';
                    END IF;
                    frozen_result := jsonb_build_object(
                        'schema_version', 'export-item-snapshot.v1',
                        'item_status', item_row.status,
                        'max_score', review_row.max_score,
                        'subtotal', review_row.subtotal,
                        'deduction_total', review_row.deduction_total,
                        'final_score', review_row.final_score,
                        'criteria_results', review_row.criteria_results,
                        'deduction_results', review_row.deduction_results,
                        'evidence', review_row.evidence,
                        'overall_feedback', review_row.feedback,
                        'change_reason', review_row.change_reason,
                        'confirmed_at', review_row.confirmed_at,
                        'attempt_number', attempt_row.attempt_number,
                        'scoring_round', attempt_row.scoring_round
                    );
                END IF;

                INSERT INTO public.export_items(
                    export_id, owner_id, assignment_id, grading_job_id,
                    grading_job_item_id, submission_id, grading_attempt_id,
                    teacher_review_id, review_revision, position, source_type,
                    original_filename, result_snapshot
                ) VALUES (
                    created_export.id, teacher_id, current_job.assignment_id, current_job.id,
                    item_row.id, item_row.submission_id, attempt_row.id,
                    CASE WHEN source_value = 'ai_suggestion' THEN NULL ELSE review_row.id END,
                    CASE WHEN source_value = 'ai_suggestion' THEN NULL
                         ELSE review_row.revision_number END,
                    item_row.position, source_value, submission_row.original_filename,
                    frozen_result
                );
                frozen_item_count := frozen_item_count + 1;
            END LOOP;
            IF frozen_item_count <> current_job.expected_item_count THEN
                RAISE EXCEPTION 'export_snapshot_invalid' USING ERRCODE = 'P0001';
            END IF;
            RETURN created_export;
        END;
        $$
        """
    )
    signature = "paper_grading_private.create_export(uuid, text, text, bytea)"
    _revoke_execute(signature)
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {TEACHER_ROLE}")


def _create_worker_functions() -> None:
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.claim_export(
            p_export_id uuid,
            p_lease_token uuid,
            p_lease_seconds integer
        )
        RETURNS public.exports
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            current_export public.exports%ROWTYPE;
            claimed_export public.exports%ROWTYPE;
            prior_claim_count bigint;
        BEGIN
            IF p_lease_token IS NULL OR p_lease_seconds NOT BETWEEN 30 AND 900 THEN
                RETURN NULL;
            END IF;
            SELECT * INTO current_export
            FROM public.exports
            WHERE id = p_export_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            IF current_export.status = 'running'
               AND current_export.lease_expires_at <= transaction_timestamp() THEN
                SELECT count(*) INTO prior_claim_count
                FROM public.audit_logs
                WHERE resource_type = 'export'
                  AND resource_id = p_export_id
                  AND action = 'export.claimed';
                IF prior_claim_count >= 3 THEN
                    UPDATE public.exports
                    SET status = 'failed', error_code = 'export_worker_lost',
                        claim_token = NULL, lease_expires_at = NULL,
                        finished_at = transaction_timestamp()
                    WHERE id = p_export_id
                    RETURNING * INTO claimed_export;
                    INSERT INTO public.audit_logs(
                        owner_id, actor_id, action, resource_type, resource_id
                    ) VALUES (
                        claimed_export.owner_id, NULL, 'export.failed',
                        'export', claimed_export.id
                    );
                    RETURN NULL;
                END IF;
            ELSIF current_export.status <> 'queued' THEN
                RETURN NULL;
            END IF;
            UPDATE public.exports
            SET status = 'running',
                started_at = COALESCE(started_at, transaction_timestamp()),
                claim_token = p_lease_token,
                lease_expires_at = transaction_timestamp()
                    + pg_catalog.make_interval(secs => p_lease_seconds)
            WHERE id = p_export_id
              AND (
                  status = 'queued'
                  OR (status = 'running' AND lease_expires_at <= transaction_timestamp())
              )
            RETURNING * INTO claimed_export;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            INSERT INTO public.audit_logs(owner_id, actor_id, action, resource_type, resource_id)
            VALUES (
                claimed_export.owner_id, NULL, 'export.claimed', 'export', claimed_export.id
            );
            RETURN claimed_export;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.complete_export(
            p_export_id uuid,
            p_lease_token uuid,
            p_object_key text,
            p_safe_filename text,
            p_file_size_bytes bigint,
            p_file_sha256 bytea
        )
        RETURNS public.exports
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE completed_export public.exports%ROWTYPE;
        BEGIN
            IF p_object_key <> 'exports/' || p_export_id::text || '/workbook.xlsx'
               OR p_safe_filename IS NULL
               OR char_length(p_safe_filename) NOT BETWEEN 6 AND 255
               OR p_safe_filename NOT LIKE '%.xlsx'
               OR p_safe_filename ~ '[/\\\\]'
               OR p_file_size_bytes <= 0
               OR octet_length(p_file_sha256) <> 32 THEN
                RETURN NULL;
            END IF;
            UPDATE public.exports
            SET status = 'completed', object_key = p_object_key,
                safe_filename = p_safe_filename, file_size_bytes = p_file_size_bytes,
                file_sha256 = p_file_sha256, claim_token = NULL,
                lease_expires_at = NULL, finished_at = transaction_timestamp()
            WHERE id = p_export_id AND status = 'running'
              AND claim_token = p_lease_token
              AND lease_expires_at > transaction_timestamp()
            RETURNING * INTO completed_export;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            INSERT INTO public.audit_logs(owner_id, actor_id, action, resource_type, resource_id)
            VALUES (
                completed_export.owner_id, NULL, 'export.completed',
                'export', completed_export.id
            );
            RETURN completed_export;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.fail_export(
            p_export_id uuid,
            p_lease_token uuid,
            p_error_code text
        )
        RETURNS public.exports
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE failed_export public.exports%ROWTYPE;
        BEGIN
            IF p_error_code IS NULL OR p_error_code !~ '^[a-z][a-z0-9_]{0,127}$' THEN
                RETURN NULL;
            END IF;
            UPDATE public.exports
            SET status = 'failed', error_code = p_error_code,
                claim_token = NULL, lease_expires_at = NULL,
                finished_at = transaction_timestamp()
            WHERE id = p_export_id AND status = 'running'
              AND claim_token = p_lease_token
              AND lease_expires_at > transaction_timestamp()
            RETURNING * INTO failed_export;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            INSERT INTO public.audit_logs(owner_id, actor_id, action, resource_type, resource_id)
            VALUES (
                failed_export.owner_id, NULL, 'export.failed', 'export', failed_export.id
            );
            RETURN failed_export;
        END;
        $$
        """
    )
    for signature in (
        "paper_grading_private.claim_export(uuid, uuid, integer)",
        "paper_grading_private.complete_export(uuid, uuid, text, text, bigint, bytea)",
        "paper_grading_private.fail_export(uuid, uuid, text)",
    ):
        _revoke_execute(signature)
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {EXPORT_WORKER_ROLE}")


def _create_worker_role() -> None:
    op.execute(
        f"""
        DO $paper_grading$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{EXPORT_WORKER_ROLE}'
            ) THEN
                CREATE ROLE {EXPORT_WORKER_ROLE} LOGIN NOINHERIT NOBYPASSRLS;
            END IF;
        END;
        $paper_grading$
        """
    )
    op.execute(f"ALTER ROLE {EXPORT_WORKER_ROLE} LOGIN NOINHERIT NOBYPASSRLS")
    op.execute(f"GRANT {EXPORT_WORKER_ROLE} TO postgres")
    op.execute(f"GRANT USAGE ON SCHEMA public, paper_grading_private TO {EXPORT_WORKER_ROLE}")
    op.execute(f"GRANT SELECT ON TABLE public.exports, public.export_items TO {EXPORT_WORKER_ROLE}")
    op.execute(
        "CREATE POLICY exports_export_worker_select ON public.exports "
        f"FOR SELECT TO {EXPORT_WORKER_ROLE} USING (true)"
    )
    op.execute(
        "CREATE POLICY export_items_export_worker_select ON public.export_items "
        f"FOR SELECT TO {EXPORT_WORKER_ROLE} USING (true)"
    )


def upgrade() -> None:
    """增加不可变快照、原子创建和独立导出 Worker。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.exports LIMIT 1) THEN
                RAISE EXCEPTION 'stage twelve requires empty legacy exports';
            END IF;
        END;
        $paper_grading$
        """
    )
    op.drop_constraint(op.f("exports_result_check"), "exports", type_="check")
    op.drop_constraint(op.f("exports_audit_metadata_check"), "exports", type_="check")
    op.add_column("exports", sa.Column("request_hash", sa.LargeBinary(32), nullable=False))
    op.add_column("exports", sa.Column("workbook_schema_version", sa.Text(), nullable=False))
    op.add_column(
        "exports",
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("exports", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("exports", sa.Column("claim_token", sa.Uuid()))
    op.add_column("exports", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("exports", sa.Column("safe_filename", sa.Text()))
    op.add_column("exports", sa.Column("file_size_bytes", sa.BigInteger()))
    op.add_column("exports", sa.Column("file_sha256", sa.LargeBinary(32)))
    op.create_unique_constraint(
        op.f("exports_id_owner_id_grading_job_id_key"),
        "exports",
        ["id", "owner_id", "grading_job_id"],
    )
    op.create_check_constraint(
        op.f("exports_request_snapshot_check"),
        "exports",
        "btrim(idempotency_key) <> '' and octet_length(request_hash) = 32 "
        "and btrim(workbook_schema_version) <> '' "
        "and jsonb_typeof(audit_metadata) = 'object'",
    )
    op.create_check_constraint(
        op.f("exports_result_check"),
        "exports",
        "(status = 'queued' and started_at is null and claim_token is null "
        "and lease_expires_at is null and object_key is null and safe_filename is null "
        "and file_size_bytes is null and file_sha256 is null and error_code is null "
        "and finished_at is null) or "
        "(status = 'running' and started_at is not null and claim_token is not null "
        "and lease_expires_at is not null and object_key is null and safe_filename is null "
        "and file_size_bytes is null and file_sha256 is null and error_code is null "
        "and finished_at is null) or "
        "(status = 'completed' and started_at is not null and claim_token is null "
        "and lease_expires_at is null and object_key is not null "
        "and safe_filename is not null and file_size_bytes > 0 "
        "and octet_length(file_sha256) = 32 and error_code is null "
        "and finished_at is not null) or "
        "(status = 'failed' and started_at is not null and claim_token is null "
        "and lease_expires_at is null and object_key is null and safe_filename is null "
        "and file_size_bytes is null and file_sha256 is null "
        "and error_code ~ '^[a-z][a-z0-9_]{0,127}$' and finished_at is not null)",
    )
    op.create_check_constraint(
        op.f("exports_object_key_check"),
        "exports",
        "object_key is null or object_key = 'exports/' || id::text || '/workbook.xlsx'",
    )
    op.create_check_constraint(
        op.f("exports_safe_filename_check"),
        "exports",
        "safe_filename is null or (char_length(safe_filename) between 6 and 255 "
        "and safe_filename like '%.xlsx' and safe_filename !~ '[/\\\\]')",
    )
    op.create_index(
        "exports_dispatch_idx",
        "exports",
        ["status", "lease_expires_at", "created_at"],
        postgresql_where=sa.text("status in ('queued', 'running')"),
    )
    op.create_index(
        "exports_object_key_idx",
        "exports",
        ["object_key"],
        unique=True,
        postgresql_where=sa.text("object_key is not null"),
    )

    op.create_table(
        "export_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("grading_job_id", sa.Uuid(), nullable=False),
        sa.Column("grading_job_item_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("grading_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_review_id", sa.Uuid()),
        sa.Column("review_revision", sa.Integer()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("result_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name=op.f("export_items_position_check")),
        sa.CheckConstraint(
            "source_type in ('ai_suggestion', 'teacher_draft', 'teacher_confirmed')",
            name=op.f("export_items_source_type_check"),
        ),
        sa.CheckConstraint(
            "(source_type = 'ai_suggestion' and teacher_review_id is null "
            "and review_revision is null) or "
            "(source_type in ('teacher_draft', 'teacher_confirmed') "
            "and teacher_review_id is not null and review_revision > 0)",
            name=op.f("export_items_review_source_check"),
        ),
        sa.CheckConstraint(
            "char_length(original_filename) between 1 and 255 and btrim(original_filename) <> ''",
            name=op.f("export_items_original_filename_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_snapshot) = 'object' "
            "and result_snapshot ->> 'schema_version' = 'export-item-snapshot.v1'",
            name=op.f("export_items_result_snapshot_check"),
        ),
        sa.ForeignKeyConstraint(
            ["export_id", "owner_id", "grading_job_id"],
            ["exports.id", "exports.owner_id", "exports.grading_job_id"],
            name=op.f("export_items_export_id_owner_id_grading_job_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("export_items_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["grading_job_item_id", "owner_id"],
            ["grading_job_items.id", "grading_job_items.owner_id"],
            name=op.f("export_items_grading_job_item_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "assignment_id", "owner_id"],
            ["submissions.id", "submissions.assignment_id", "submissions.owner_id"],
            name=op.f("export_items_submission_id_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["grading_attempt_id", "grading_job_item_id", "owner_id"],
            [
                "grading_attempts.id",
                "grading_attempts.grading_job_item_id",
                "grading_attempts.owner_id",
            ],
            name=op.f("export_items_grading_attempt_id_grading_job_item_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_review_id"],
            ["teacher_reviews.id"],
            name=op.f("export_items_teacher_review_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("export_items_pkey")),
        sa.UniqueConstraint(
            "export_id", "position", name=op.f("export_items_export_id_position_key")
        ),
        sa.UniqueConstraint(
            "export_id",
            "grading_job_item_id",
            name=op.f("export_items_export_id_grading_job_item_id_key"),
        ),
    )
    op.create_index("export_items_owner_created_idx", "export_items", ["owner_id", "created_at"])
    op.create_index("export_items_export_position_idx", "export_items", ["export_id", "position"])
    op.create_index(
        "export_items_export_owner_job_idx",
        "export_items",
        ["export_id", "owner_id", "grading_job_id"],
    )
    op.create_index("export_items_job_owner_idx", "export_items", ["grading_job_id", "owner_id"])
    op.create_index(
        "export_items_item_owner_idx",
        "export_items",
        ["grading_job_item_id", "owner_id"],
    )
    op.create_index(
        "export_items_submission_assignment_owner_idx",
        "export_items",
        ["submission_id", "assignment_id", "owner_id"],
    )
    op.create_index(
        "export_items_attempt_item_owner_idx",
        "export_items",
        ["grading_attempt_id", "grading_job_item_id", "owner_id"],
    )
    op.create_index("export_items_review_idx", "export_items", ["teacher_review_id"])
    op.execute("ALTER TABLE public.export_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.export_items FORCE ROW LEVEL SECURITY")
    for role in ("anon", "authenticated", "service_role", TEACHER_ROLE):
        op.execute(f"REVOKE ALL PRIVILEGES ON TABLE public.export_items FROM {role}")
    op.execute(f"GRANT SELECT ON TABLE public.export_items TO {TEACHER_ROLE}")
    op.execute(
        "CREATE POLICY export_items_teacher_select ON public.export_items "
        f"FOR SELECT TO {TEACHER_ROLE} "
        "USING (owner_id = (SELECT paper_grading_private.current_active_teacher_id()))"
    )
    op.execute(f"REVOKE INSERT ON TABLE public.exports FROM {TEACHER_ROLE}")
    op.execute("DROP POLICY exports_teacher_insert ON public.exports")

    _create_export_protection()
    _create_teacher_function()
    _create_worker_role()
    _create_worker_functions()


def downgrade() -> None:
    """仅在尚无导出历史时完整恢复阶段十一结构和权限。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.exports LIMIT 1)
               OR EXISTS (SELECT 1 FROM public.export_items LIMIT 1) THEN
                RAISE EXCEPTION 'cannot remove stage twelve while export history exists';
            END IF;
        END;
        $paper_grading$
        """
    )
    for signature in (
        "paper_grading_private.fail_export(uuid, uuid, text)",
        "paper_grading_private.complete_export(uuid, uuid, text, text, bigint, bytea)",
        "paper_grading_private.claim_export(uuid, uuid, integer)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    op.execute("DROP FUNCTION paper_grading_private.create_export(uuid, text, text, bytea)")
    op.execute("DROP POLICY export_items_export_worker_select ON public.export_items")
    op.execute("DROP POLICY exports_export_worker_select ON public.exports")
    op.execute(
        f"REVOKE SELECT ON TABLE public.exports, public.export_items FROM {EXPORT_WORKER_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public, paper_grading_private FROM {EXPORT_WORKER_ROLE}")
    op.execute(f"REVOKE {EXPORT_WORKER_ROLE} FROM postgres")
    op.execute(f"DROP ROLE IF EXISTS {EXPORT_WORKER_ROLE}")
    op.execute("DROP TRIGGER export_items_reject_mutation ON public.export_items")
    op.execute("DROP FUNCTION public.paper_grading_reject_export_item_mutation()")
    op.execute("DROP TRIGGER exports_protect_history ON public.exports")
    op.execute("DROP FUNCTION public.paper_grading_protect_export_history()")
    op.execute("DROP POLICY export_items_teacher_select ON public.export_items")
    op.execute("DROP TABLE public.export_items")
    op.execute(
        "CREATE POLICY exports_teacher_insert ON public.exports "
        "FOR INSERT TO paper_grading_teacher_api "
        "WITH CHECK (owner_id = (SELECT paper_grading_private.current_active_teacher_id()))"
    )
    op.execute(f"GRANT INSERT ON TABLE public.exports TO {TEACHER_ROLE}")
    op.drop_index("exports_object_key_idx", table_name="exports")
    op.drop_index("exports_dispatch_idx", table_name="exports")
    op.drop_constraint(op.f("exports_safe_filename_check"), "exports", type_="check")
    op.drop_constraint(op.f("exports_object_key_check"), "exports", type_="check")
    op.drop_constraint(op.f("exports_result_check"), "exports", type_="check")
    op.drop_constraint(op.f("exports_request_snapshot_check"), "exports", type_="check")
    op.drop_constraint(op.f("exports_id_owner_id_grading_job_id_key"), "exports", type_="unique")
    for column_name in (
        "file_sha256",
        "file_size_bytes",
        "safe_filename",
        "lease_expires_at",
        "claim_token",
        "started_at",
        "snapshot_at",
        "workbook_schema_version",
        "request_hash",
    ):
        op.drop_column("exports", column_name)
    op.create_check_constraint(
        op.f("exports_result_check"),
        "exports",
        "btrim(idempotency_key) <> '' and "
        "((status = 'completed' and object_key is not null and finished_at is not null) or "
        "(status = 'failed' and error_code is not null and finished_at is not null) or "
        "(status in ('queued', 'running') and finished_at is null))",
    )
    op.create_check_constraint(
        op.f("exports_audit_metadata_check"),
        "exports",
        "jsonb_typeof(audit_metadata) = 'object'",
    )
