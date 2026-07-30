"""建立教师复核草稿与原子确认边界。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260719_0015"
down_revision: str | None = "20260718_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEACHER_ROLE = "paper_grading_teacher_api"
API_ROLES = ("PUBLIC", "anon", "authenticated", "service_role")


def _revoke_execute(signature: str) -> None:
    for role in API_ROLES:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {role}")


def _create_item_protection(*, stage_eleven: bool) -> None:
    terminal_sources = (
        "'needs_review', 'failed'" if stage_eleven else "'needs_review', 'completed', 'failed'"
    )
    review_completion = (
        "OR (OLD.status = 'needs_review' AND NEW.status = 'completed')" if stage_eleven else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_protect_job_item()
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
                {review_completion}
                OR (OLD.status IN ({terminal_sources}) AND NEW.status = 'queued')
            ) THEN
                RAISE EXCEPTION 'invalid grading job item status transition'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status IN ({terminal_sources}) AND NEW.status = 'queued' THEN
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


def _create_review_protection(*, stage_eleven: bool) -> None:
    revision_identity = "" if stage_eleven else "NEW.revision_number,"
    old_revision_identity = "" if stage_eleven else "OLD.revision_number,"
    revision_guard = (
        """
            IF NEW.status = 'draft'
               AND NEW.revision_number <> OLD.revision_number + 1 THEN
                RAISE EXCEPTION 'draft review revision must advance exactly once'
                    USING ERRCODE = '55000';
            ELSIF NEW.status = 'confirmed'
                  AND NEW.revision_number <> OLD.revision_number THEN
                RAISE EXCEPTION 'confirmed review must keep the saved revision'
                    USING ERRCODE = '55000';
            END IF;
        """
        if stage_eleven
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.paper_grading_protect_review_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = ''
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'teacher review history cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'confirmed' THEN
                RAISE EXCEPTION 'confirmed teacher review is immutable'
                    USING ERRCODE = '55000';
            END IF;
            {revision_guard}
            IF ROW(
                NEW.id,
                NEW.owner_id,
                NEW.grading_job_item_id,
                NEW.grading_attempt_id,
                {revision_identity}
                NEW.max_score,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.grading_job_item_id,
                OLD.grading_attempt_id,
                {old_revision_identity}
                OLD.max_score,
                OLD.created_at
            ) THEN
                RAISE EXCEPTION 'teacher review identity and score ceiling are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _revoke_execute("public.paper_grading_protect_review_history()")


def _create_control_function(*, stage_eleven: bool) -> None:
    retry_statuses = (
        "'needs_review', 'failed'" if stage_eleven else "'needs_review', 'completed', 'failed'"
    )
    confirmed_guard = (
        """
                  AND NOT EXISTS (
                      SELECT 1 FROM public.teacher_reviews AS review
                      WHERE review.grading_job_item_id = target_item_id
                        AND review.owner_id = teacher_id
                        AND review.status = 'confirmed'
                  )"""
        if stage_eleven
        else ""
    )
    cancellable_statuses = (
        "'queued', 'running', 'paused'"
        if stage_eleven
        else "'queued', 'running', 'paused', 'needs_review'"
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION paper_grading_private.control_grading_job(
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
                  AND current_job.status IN ({cancellable_statuses}) THEN
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
                  AND owner_id = teacher_id AND status IN ({retry_statuses})
                  {confirmed_guard};
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
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.control_grading_job(uuid, text, uuid) "
        f"TO {TEACHER_ROLE}"
    )


def _create_payload_validator() -> None:
    op.execute(
        r"""
        CREATE FUNCTION paper_grading_private.validate_teacher_review_payload(
            target_criteria jsonb,
            target_deductions jsonb,
            target_evidence jsonb,
            target_feedback text,
            target_change_reason text,
            target_subtotal numeric,
            target_deduction_total numeric,
            target_final_score numeric,
            rubric jsonb,
            attempt_criteria jsonb,
            attempt_deductions jsonb,
            attempt_feedback text
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            criterion_row record;
            deduction_row record;
            evidence_row jsonb;
            calculated_subtotal numeric := 0;
            calculated_deduction_total numeric := 0;
            ai_criteria jsonb;
            ai_deductions jsonb;
            ai_evidence jsonb;
            score_step numeric;
        BEGIN
            IF jsonb_typeof(target_criteria) <> 'array'
               OR jsonb_typeof(target_deductions) <> 'array'
               OR jsonb_typeof(target_evidence) <> 'array'
               OR jsonb_typeof(rubric) <> 'object'
               OR btrim(target_feedback) = '' THEN
                RAISE EXCEPTION 'review payload shape is invalid'
                    USING ERRCODE = '23514';
            END IF;
            score_step := (rubric ->> 'score_step')::numeric;
            IF jsonb_array_length(target_criteria) <> jsonb_array_length(rubric -> 'dimensions')
               OR jsonb_array_length(target_deductions)
                  <> jsonb_array_length(rubric -> 'deductions') THEN
                RAISE EXCEPTION 'review result ids do not match rubric'
                    USING ERRCODE = '23514';
            END IF;
            FOR criterion_row IN
                SELECT criterion.value AS criterion, dimension.value AS dimension
                FROM jsonb_array_elements(target_criteria) WITH ORDINALITY AS criterion(value, ord)
                FULL JOIN jsonb_array_elements(rubric -> 'dimensions') WITH ORDINALITY
                    AS dimension(value, ord) USING (ord)
                ORDER BY ord
            LOOP
                IF criterion_row.criterion IS NULL OR criterion_row.dimension IS NULL
                   OR (SELECT count(*) FROM jsonb_object_keys(criterion_row.criterion)) <> 4
                   OR criterion_row.criterion ->> 'dimension_id'
                      <> criterion_row.dimension ->> 'id'
                   OR criterion_row.criterion ->> 'score'
                      !~ '^(0|[1-9][0-9]*)(\.[0-9]{1,4})?$'
                   OR btrim(criterion_row.criterion ->> 'reason') = ''
                   OR jsonb_typeof(criterion_row.criterion -> 'revision_suggestions') <> 'array'
                   OR jsonb_array_length(criterion_row.criterion -> 'revision_suggestions') = 0
                   OR (criterion_row.criterion ->> 'score')::numeric < 0
                   OR (criterion_row.criterion ->> 'score')::numeric
                      > (criterion_row.dimension ->> 'max_score')::numeric
                   OR mod((criterion_row.criterion ->> 'score')::numeric, score_step) <> 0 THEN
                    RAISE EXCEPTION 'review criterion violates rubric'
                        USING ERRCODE = '23514';
                END IF;
                calculated_subtotal := calculated_subtotal
                    + (criterion_row.criterion ->> 'score')::numeric;
            END LOOP;
            FOR deduction_row IN
                SELECT result.value AS result, deduction.value AS deduction
                FROM jsonb_array_elements(target_deductions) WITH ORDINALITY AS result(value, ord)
                FULL JOIN jsonb_array_elements(rubric -> 'deductions') WITH ORDINALITY
                    AS deduction(value, ord) USING (ord)
                ORDER BY ord
            LOOP
                IF deduction_row.result IS NULL OR deduction_row.deduction IS NULL
                   OR (SELECT count(*) FROM jsonb_object_keys(deduction_row.result)) <> 3
                   OR deduction_row.result ->> 'deduction_id'
                      <> deduction_row.deduction ->> 'id'
                   OR jsonb_typeof(deduction_row.result -> 'applied') <> 'boolean'
                   OR btrim(deduction_row.result ->> 'reason') = '' THEN
                    RAISE EXCEPTION 'review deduction violates rubric'
                        USING ERRCODE = '23514';
                END IF;
                IF (deduction_row.result ->> 'applied')::boolean THEN
                    calculated_deduction_total := calculated_deduction_total
                        + (deduction_row.deduction ->> 'points')::numeric;
                END IF;
            END LOOP;
            FOR evidence_row IN SELECT value FROM jsonb_array_elements(target_evidence)
            LOOP
                IF (SELECT count(*) FROM jsonb_object_keys(evidence_row)) <> 4
                   OR evidence_row ->> 'target_type' NOT IN ('dimension', 'deduction')
                   OR evidence_row ->> 'block_id' !~ '^b[0-9]{6}$'
                   OR btrim(evidence_row ->> 'quote') = ''
                   OR (
                       evidence_row ->> 'target_type' = 'dimension'
                       AND NOT EXISTS (
                           SELECT 1 FROM jsonb_array_elements(target_criteria) AS criterion
                           WHERE criterion ->> 'dimension_id' = evidence_row ->> 'target_id'
                       )
                   )
                   OR (
                       evidence_row ->> 'target_type' = 'deduction'
                       AND NOT EXISTS (
                           SELECT 1 FROM jsonb_array_elements(target_deductions) AS deduction
                           WHERE deduction ->> 'deduction_id' = evidence_row ->> 'target_id'
                       )
                   ) THEN
                    RAISE EXCEPTION 'review evidence target is invalid'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            IF target_subtotal <> calculated_subtotal
               OR target_deduction_total <> calculated_deduction_total
               OR target_final_score <> greatest(
                    0, calculated_subtotal - calculated_deduction_total
               ) THEN
                RAISE EXCEPTION 'review total must be calculated from rubric'
                    USING ERRCODE = '23514';
            END IF;

            SELECT coalesce(jsonb_agg(value - 'evidence' ORDER BY ord), '[]'::jsonb)
            INTO ai_criteria
            FROM jsonb_array_elements(attempt_criteria) WITH ORDINALITY AS item(value, ord);
            SELECT coalesce(jsonb_agg(value - 'evidence' ORDER BY ord), '[]'::jsonb)
            INTO ai_deductions
            FROM jsonb_array_elements(attempt_deductions) WITH ORDINALITY AS item(value, ord);
            SELECT coalesce(
                jsonb_agg(entry ORDER BY group_ord, item_ord, evidence_ord),
                '[]'::jsonb
            )
            INTO ai_evidence
            FROM (
                SELECT 0 AS group_ord, criterion_ord AS item_ord,
                       quote_ord AS evidence_ord,
                       jsonb_build_object(
                           'target_type', 'dimension',
                           'target_id', criterion ->> 'dimension_id',
                           'block_id', quote ->> 'block_id',
                           'quote', quote ->> 'quote'
                       ) AS entry
                FROM jsonb_array_elements(attempt_criteria) WITH ORDINALITY
                    AS criteria(criterion, criterion_ord)
                CROSS JOIN LATERAL jsonb_array_elements(criterion -> 'evidence') WITH ORDINALITY
                    AS quotes(quote, quote_ord)
                UNION ALL
                SELECT 1, deduction_ord, quote_ord,
                       jsonb_build_object(
                           'target_type', 'deduction',
                           'target_id', deduction ->> 'deduction_id',
                           'block_id', quote ->> 'block_id',
                           'quote', quote ->> 'quote'
                       )
                FROM jsonb_array_elements(attempt_deductions) WITH ORDINALITY
                    AS deductions(deduction, deduction_ord)
                CROSS JOIN LATERAL jsonb_array_elements(deduction -> 'evidence') WITH ORDINALITY
                    AS quotes(quote, quote_ord)
            ) AS flattened;
            IF target_change_reason IS NULL
               AND (
                   target_criteria IS DISTINCT FROM ai_criteria
                   OR target_deductions IS DISTINCT FROM ai_deductions
                   OR target_evidence IS DISTINCT FROM ai_evidence
                   OR target_feedback IS DISTINCT FROM attempt_feedback
               ) THEN
                RAISE EXCEPTION 'review change reason is required'
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$
        """
    )
    _revoke_execute(
        "paper_grading_private.validate_teacher_review_payload("
        "jsonb, jsonb, jsonb, text, text, numeric, numeric, numeric, "
        "jsonb, jsonb, jsonb, text)"
    )


def _create_save_function() -> None:
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.save_teacher_review_draft(
            target_item_id uuid,
            target_attempt_id uuid,
            target_criteria jsonb,
            target_deductions jsonb,
            target_evidence jsonb,
            target_feedback text,
            target_change_reason text,
            target_subtotal numeric,
            target_deduction_total numeric,
            target_final_score numeric
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            teacher_id uuid;
            target_job_id uuid;
            current_item public.grading_job_items%ROWTYPE;
            current_job public.grading_jobs%ROWTYPE;
            current_submission public.submissions%ROWTYPE;
            current_rubric public.rubric_versions%ROWTYPE;
            current_attempt public.grading_attempts%ROWTYPE;
            current_review public.teacher_reviews%ROWTYPE;
            next_revision integer;
        BEGIN
            teacher_id := paper_grading_private.current_active_teacher_id();
            IF teacher_id IS NULL THEN
                RETURN NULL;
            END IF;
            SELECT grading_job_id INTO target_job_id
            FROM public.grading_job_items
            WHERE id = target_item_id AND owner_id = teacher_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            SELECT * INTO current_job FROM public.grading_jobs
            WHERE id = target_job_id AND owner_id = teacher_id FOR UPDATE;
            SELECT * INTO current_item FROM public.grading_job_items
            WHERE id = target_item_id AND grading_job_id = target_job_id
              AND owner_id = teacher_id FOR UPDATE;
            IF NOT FOUND OR current_item.status <> 'needs_review' THEN
                RETURN NULL;
            END IF;
            SELECT * INTO current_attempt FROM public.grading_attempts
            WHERE id = target_attempt_id
              AND grading_job_item_id = target_item_id
              AND owner_id = teacher_id
              AND status = 'succeeded'
              AND scoring_round = current_item.dispatch_version
              AND id = (
                  SELECT attempt.id FROM public.grading_attempts AS attempt
                  WHERE attempt.grading_job_item_id = target_item_id
                    AND attempt.owner_id = teacher_id
                    AND attempt.status = 'succeeded'
                    AND attempt.scoring_round = current_item.dispatch_version
                  ORDER BY attempt.attempt_number DESC LIMIT 1
              )
            FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            SELECT * INTO current_submission FROM public.submissions
            WHERE id = current_item.submission_id
              AND assignment_id = current_item.assignment_id
              AND owner_id = teacher_id;
            SELECT * INTO current_rubric FROM public.rubric_versions
            WHERE id = current_job.rubric_version_id
              AND assignment_id = current_job.assignment_id
              AND owner_id = teacher_id;
            IF current_submission.status <> 'ready'
               OR current_submission.extracted_object_key IS NULL
               OR current_rubric.structured_rubric IS NULL
               OR current_rubric.status NOT IN ('confirmed', 'superseded')
               OR current_attempt.max_score <> current_rubric.total_score THEN
                RETURN NULL;
            END IF;
            PERFORM paper_grading_private.validate_teacher_review_payload(
                target_criteria, target_deductions, target_evidence,
                target_feedback, target_change_reason, target_subtotal,
                target_deduction_total, target_final_score,
                current_rubric.structured_rubric,
                current_attempt.criteria_results,
                current_attempt.deduction_results,
                current_attempt.overall_feedback
            );
            SELECT * INTO current_review FROM public.teacher_reviews
            WHERE grading_attempt_id = target_attempt_id
              AND grading_job_item_id = target_item_id
              AND owner_id = teacher_id
            FOR UPDATE;
            IF FOUND THEN
                IF current_review.status <> 'draft' THEN
                    RETURN NULL;
                END IF;
                UPDATE public.teacher_reviews
                SET revision_number = current_review.revision_number + 1,
                    criteria_results = target_criteria,
                    deduction_results = target_deductions,
                    evidence = target_evidence,
                    feedback = target_feedback,
                    change_reason = target_change_reason,
                    subtotal = target_subtotal,
                    deduction_total = target_deduction_total,
                    final_score = target_final_score
                WHERE id = current_review.id;
                RETURN current_review.id;
            END IF;
            SELECT coalesce(max(revision_number), 0) + 1 INTO next_revision
            FROM public.teacher_reviews
            WHERE grading_job_item_id = target_item_id AND owner_id = teacher_id;
            INSERT INTO public.teacher_reviews(
                owner_id, grading_job_item_id, grading_attempt_id,
                revision_number, status, max_score, final_score,
                subtotal, deduction_total, criteria_results, deduction_results,
                feedback, evidence, change_reason
            ) VALUES (
                teacher_id, target_item_id, target_attempt_id,
                next_revision, 'draft', current_attempt.max_score, target_final_score,
                target_subtotal, target_deduction_total, target_criteria,
                target_deductions, target_feedback, target_evidence,
                target_change_reason
            ) RETURNING id INTO current_review.id;
            RETURN current_review.id;
        END;
        $$
        """
    )
    signature = (
        "paper_grading_private.save_teacher_review_draft("
        "uuid, uuid, jsonb, jsonb, jsonb, text, text, numeric, numeric, numeric)"
    )
    _revoke_execute(signature)
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {TEACHER_ROLE}")


def _create_confirm_function() -> None:
    op.execute(
        """
        CREATE FUNCTION paper_grading_private.confirm_teacher_reviews(
            target_reviews jsonb
        )
        RETURNS uuid[]
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            teacher_id uuid;
            target_count integer;
            confirmed_count integer;
            review_row record;
            job_id uuid;
            result_ids uuid[];
        BEGIN
            teacher_id := paper_grading_private.current_active_teacher_id();
            IF teacher_id IS NULL OR jsonb_typeof(target_reviews) <> 'array' THEN
                RETURN NULL;
            END IF;
            target_count := jsonb_array_length(target_reviews);
            IF target_count < 1 OR target_count > 100
               OR EXISTS (
                   SELECT 1 FROM jsonb_array_elements(target_reviews) AS items(entry)
                   WHERE (SELECT count(*) FROM jsonb_object_keys(entry)) <> 2
                      OR entry ->> 'review_id' !~
                         '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                      OR entry ->> 'revision_number' !~ '^[1-9][0-9]*$'
               )
               OR (
                   SELECT count(DISTINCT entry ->> 'review_id')
                   FROM jsonb_array_elements(target_reviews) AS items(entry)
               ) <> target_count THEN
                RAISE EXCEPTION 'review confirmation request is invalid'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM 1 FROM public.grading_jobs AS job
            WHERE job.owner_id = teacher_id
              AND job.id IN (
                  SELECT item.grading_job_id
                  FROM public.teacher_reviews AS review
                  JOIN public.grading_job_items AS item
                    ON item.id = review.grading_job_item_id
                   AND item.owner_id = review.owner_id
                  WHERE review.id IN (
                      SELECT (entry ->> 'review_id')::uuid
                      FROM jsonb_array_elements(target_reviews) AS items(entry)
                  )
              )
            ORDER BY job.id FOR UPDATE;
            PERFORM 1 FROM public.grading_job_items AS item
            WHERE item.owner_id = teacher_id
              AND item.id IN (
                  SELECT review.grading_job_item_id
                  FROM public.teacher_reviews AS review
                  WHERE review.id IN (
                      SELECT (entry ->> 'review_id')::uuid
                      FROM jsonb_array_elements(target_reviews) AS items(entry)
                  )
              )
            ORDER BY item.id FOR UPDATE;
            PERFORM 1 FROM public.grading_attempts AS attempt
            WHERE attempt.owner_id = teacher_id
              AND attempt.id IN (
                  SELECT review.grading_attempt_id
                  FROM public.teacher_reviews AS review
                  WHERE review.id IN (
                      SELECT (entry ->> 'review_id')::uuid
                      FROM jsonb_array_elements(target_reviews) AS items(entry)
                  )
              )
            ORDER BY attempt.id FOR UPDATE;
            PERFORM 1 FROM public.teacher_reviews AS review
            WHERE review.owner_id = teacher_id
              AND review.id IN (
                  SELECT (entry ->> 'review_id')::uuid
                  FROM jsonb_array_elements(target_reviews) AS items(entry)
              )
            ORDER BY review.id FOR UPDATE;

            SELECT count(*), count(*) FILTER (WHERE review.status = 'confirmed')
            INTO target_count, confirmed_count
            FROM jsonb_array_elements(target_reviews) AS items(entry)
            JOIN public.teacher_reviews AS review
              ON review.id = (entry ->> 'review_id')::uuid
             AND review.revision_number = (entry ->> 'revision_number')::integer
             AND review.owner_id = teacher_id;
            IF target_count <> jsonb_array_length(target_reviews) THEN
                RETURN NULL;
            END IF;
            IF confirmed_count = target_count THEN
                SELECT array_agg((entry ->> 'review_id')::uuid ORDER BY ord)
                INTO result_ids
                FROM jsonb_array_elements(target_reviews) WITH ORDINALITY AS item(entry, ord);
                RETURN result_ids;
            ELSIF confirmed_count <> 0 THEN
                RAISE EXCEPTION 'review confirmation conflicts with confirmed data'
                    USING ERRCODE = '40001';
            END IF;

            FOR review_row IN
                SELECT review.*, item.status AS item_status,
                       item.dispatch_version, item.submission_id,
                       item.grading_job_id, item.assignment_id,
                       job.rubric_version_id,
                       submission.status AS submission_status,
                       submission.extracted_object_key,
                       rubric.status AS rubric_status,
                       rubric.structured_rubric,
                       rubric.total_score AS rubric_total,
                       attempt.status AS attempt_status,
                       attempt.scoring_round,
                       attempt.criteria_results AS attempt_criteria,
                       attempt.deduction_results AS attempt_deductions,
                       attempt.overall_feedback AS attempt_feedback
                FROM jsonb_array_elements(target_reviews) AS items(entry)
                JOIN public.teacher_reviews AS review
                  ON review.id = (entry ->> 'review_id')::uuid
                 AND review.revision_number = (entry ->> 'revision_number')::integer
                 AND review.owner_id = teacher_id
                JOIN public.grading_job_items AS item
                  ON item.id = review.grading_job_item_id
                 AND item.owner_id = review.owner_id
                JOIN public.grading_jobs AS job
                  ON job.id = item.grading_job_id
                 AND job.owner_id = item.owner_id
                JOIN public.submissions AS submission
                  ON submission.id = item.submission_id
                 AND submission.assignment_id = item.assignment_id
                 AND submission.owner_id = item.owner_id
                JOIN public.rubric_versions AS rubric
                  ON rubric.id = job.rubric_version_id
                 AND rubric.assignment_id = job.assignment_id
                 AND rubric.owner_id = job.owner_id
                JOIN public.grading_attempts AS attempt
                  ON attempt.id = review.grading_attempt_id
                 AND attempt.grading_job_item_id = item.id
                 AND attempt.owner_id = item.owner_id
                ORDER BY job.id, item.id, review.id
            LOOP
                IF review_row.status <> 'draft'
                   OR review_row.item_status <> 'needs_review'
                   OR review_row.submission_status <> 'ready'
                   OR review_row.extracted_object_key IS NULL
                   OR review_row.rubric_status NOT IN ('confirmed', 'superseded')
                   OR review_row.structured_rubric IS NULL
                   OR review_row.attempt_status <> 'succeeded'
                   OR review_row.scoring_round <> review_row.dispatch_version
                   OR review_row.max_score <> review_row.rubric_total
                   OR review_row.grading_attempt_id <> (
                       SELECT attempt.id FROM public.grading_attempts AS attempt
                       WHERE attempt.grading_job_item_id = review_row.grading_job_item_id
                         AND attempt.owner_id = teacher_id
                         AND attempt.status = 'succeeded'
                         AND attempt.scoring_round = review_row.dispatch_version
                       ORDER BY attempt.attempt_number DESC LIMIT 1
                   ) THEN
                    RAISE EXCEPTION 'review confirmation state changed'
                        USING ERRCODE = '40001';
                END IF;
                PERFORM paper_grading_private.validate_teacher_review_payload(
                    review_row.criteria_results, review_row.deduction_results,
                    review_row.evidence, review_row.feedback,
                    review_row.change_reason, review_row.subtotal,
                    review_row.deduction_total, review_row.final_score,
                    review_row.structured_rubric,
                    review_row.attempt_criteria,
                    review_row.attempt_deductions,
                    review_row.attempt_feedback
                );
            END LOOP;

            UPDATE public.teacher_reviews AS review
            SET status = 'confirmed', confirmed_at = transaction_timestamp()
            WHERE review.owner_id = teacher_id
              AND review.id IN (
                  SELECT (entry ->> 'review_id')::uuid
                  FROM jsonb_array_elements(target_reviews) AS items(entry)
              );
            UPDATE public.grading_job_items AS item
            SET status = 'completed', finished_at = transaction_timestamp(),
                error_code = NULL, updated_at = transaction_timestamp()
            WHERE item.owner_id = teacher_id
              AND item.id IN (
                  SELECT review.grading_job_item_id
                  FROM public.teacher_reviews AS review
                  WHERE review.id IN (
                      SELECT (entry ->> 'review_id')::uuid
                      FROM jsonb_array_elements(target_reviews) AS items(entry)
                  )
              );
            INSERT INTO public.audit_logs(
                owner_id, actor_id, action, resource_type, resource_id, metadata
            )
            SELECT teacher_id, teacher_id, 'teacher_review.confirmed',
                   'teacher_review', review.id,
                   jsonb_build_object(
                       'job_id', item.grading_job_id,
                       'item_id', item.id,
                       'revision_number', review.revision_number,
                       'final_score', review.final_score
                   )
            FROM public.teacher_reviews AS review
            JOIN public.grading_job_items AS item
              ON item.id = review.grading_job_item_id
             AND item.owner_id = review.owner_id
            WHERE review.owner_id = teacher_id
              AND review.id IN (
                  SELECT (entry ->> 'review_id')::uuid
                  FROM jsonb_array_elements(target_reviews) AS items(entry)
              );
            FOR job_id IN
                SELECT DISTINCT item.grading_job_id
                FROM public.teacher_reviews AS review
                JOIN public.grading_job_items AS item
                  ON item.id = review.grading_job_item_id
                 AND item.owner_id = review.owner_id
                WHERE review.owner_id = teacher_id
                  AND review.id IN (
                      SELECT (entry ->> 'review_id')::uuid
                      FROM jsonb_array_elements(target_reviews) AS items(entry)
                  )
                ORDER BY item.grading_job_id
            LOOP
                IF EXISTS (
                    SELECT 1 FROM public.grading_job_items AS item
                    WHERE item.grading_job_id = job_id
                      AND item.owner_id = teacher_id
                      AND item.status <> 'completed'
                ) THEN
                    UPDATE public.grading_jobs
                    SET status = 'needs_review', finished_at = NULL,
                        state_version = state_version + 1,
                        updated_at = transaction_timestamp()
                    WHERE id = job_id AND owner_id = teacher_id;
                ELSE
                    UPDATE public.grading_jobs
                    SET status = 'completed',
                        finished_at = transaction_timestamp(),
                        state_version = state_version + 1,
                        updated_at = transaction_timestamp()
                    WHERE id = job_id AND owner_id = teacher_id;
                END IF;
            END LOOP;
            SELECT array_agg((entry ->> 'review_id')::uuid ORDER BY ord)
            INTO result_ids
            FROM jsonb_array_elements(target_reviews) WITH ORDINALITY AS item(entry, ord);
            RETURN result_ids;
        END;
        $$
        """
    )
    signature = "paper_grading_private.confirm_teacher_reviews(jsonb)"
    _revoke_execute(signature)
    op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {TEACHER_ROLE}")


def upgrade() -> None:
    """保存独立扣分结果并把确认收口封装为唯一数据库入口。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.teacher_reviews LIMIT 1) THEN
                RAISE EXCEPTION 'stage eleven requires empty teacher review table';
            END IF;
        END;
        $paper_grading$
        """
    )
    op.add_column(
        "teacher_reviews",
        sa.Column(
            "deduction_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "teacher_reviews",
        sa.Column("subtotal", sa.Numeric(10, 4), nullable=False),
    )
    op.add_column(
        "teacher_reviews",
        sa.Column("deduction_total", sa.Numeric(10, 4), nullable=False),
    )
    op.alter_column("teacher_reviews", "final_score", nullable=False)
    op.alter_column("teacher_reviews", "criteria_results", nullable=False)
    op.alter_column("teacher_reviews", "feedback", nullable=False)
    op.drop_constraint(
        op.f("teacher_reviews_confirmation_check"),
        "teacher_reviews",
        type_="check",
    )
    op.drop_constraint(
        op.f("teacher_reviews_json_shapes_check"),
        "teacher_reviews",
        type_="check",
    )
    op.create_check_constraint(
        op.f("teacher_reviews_confirmation_check"),
        "teacher_reviews",
        "(status = 'draft' and confirmed_at is null) or "
        "(status = 'confirmed' and confirmed_at is not null)",
    )
    op.create_check_constraint(
        op.f("teacher_reviews_json_shapes_check"),
        "teacher_reviews",
        "jsonb_typeof(criteria_results) = 'array' "
        "and jsonb_typeof(deduction_results) = 'array' "
        "and jsonb_typeof(evidence) = 'array'",
    )
    op.create_check_constraint(
        op.f("teacher_reviews_totals_check"),
        "teacher_reviews",
        "subtotal >= 0 and deduction_total >= 0 "
        "and final_score = greatest(0, subtotal - deduction_total)",
    )
    op.create_index(
        "teacher_reviews_one_attempt_idx",
        "teacher_reviews",
        ["grading_attempt_id"],
        unique=True,
    )
    _create_review_protection(stage_eleven=True)
    _create_item_protection(stage_eleven=True)
    _create_control_function(stage_eleven=True)
    _create_payload_validator()
    _create_save_function()
    _create_confirm_function()
    op.execute(
        "REVOKE INSERT, UPDATE ON TABLE public.teacher_reviews FROM paper_grading_teacher_api"
    )


def downgrade() -> None:
    """仅在尚无教师复核数据时恢复阶段十权限与状态机。"""

    op.execute(
        """
        DO $paper_grading$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.teacher_reviews LIMIT 1) THEN
                RAISE EXCEPTION 'cannot remove stage eleven while teacher reviews exist';
            END IF;
        END;
        $paper_grading$
        """
    )
    op.execute("DROP FUNCTION paper_grading_private.confirm_teacher_reviews(jsonb)")
    op.execute(
        "DROP FUNCTION paper_grading_private.save_teacher_review_draft("
        "uuid, uuid, jsonb, jsonb, jsonb, text, text, numeric, numeric, numeric)"
    )
    op.execute(
        "DROP FUNCTION paper_grading_private.validate_teacher_review_payload("
        "jsonb, jsonb, jsonb, text, text, numeric, numeric, numeric, "
        "jsonb, jsonb, jsonb, text)"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE public.teacher_reviews TO paper_grading_teacher_api"
    )
    _create_review_protection(stage_eleven=False)
    _create_control_function(stage_eleven=False)
    _create_item_protection(stage_eleven=False)
    op.drop_index("teacher_reviews_one_attempt_idx")
    op.drop_constraint(op.f("teacher_reviews_totals_check"), "teacher_reviews", type_="check")
    op.drop_constraint(
        op.f("teacher_reviews_json_shapes_check"),
        "teacher_reviews",
        type_="check",
    )
    op.drop_constraint(
        op.f("teacher_reviews_confirmation_check"),
        "teacher_reviews",
        type_="check",
    )
    op.create_check_constraint(
        op.f("teacher_reviews_confirmation_check"),
        "teacher_reviews",
        "(status = 'draft' and confirmed_at is null) or "
        "(status = 'confirmed' and confirmed_at is not null and final_score is not null "
        "and criteria_results is not null and feedback is not null)",
    )
    op.create_check_constraint(
        op.f("teacher_reviews_json_shapes_check"),
        "teacher_reviews",
        "(criteria_results is null or jsonb_typeof(criteria_results) = 'array') "
        "and jsonb_typeof(evidence) = 'array'",
    )
    op.alter_column("teacher_reviews", "feedback", nullable=True)
    op.alter_column("teacher_reviews", "criteria_results", nullable=True)
    op.alter_column("teacher_reviews", "final_score", nullable=True)
    op.drop_column("teacher_reviews", "deduction_total")
    op.drop_column("teacher_reviews", "subtotal")
    op.drop_column("teacher_reviews", "deduction_results")
