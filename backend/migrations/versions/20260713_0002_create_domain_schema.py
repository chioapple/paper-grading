"""建立阶段 2 业务数据模型、约束和索引。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260713_0002"
down_revision: str | None = "20260713_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建可审计批改流水线所需的 11 张表。"""

    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'invited'"), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(display_name) <> ''", name=op.f("profiles_display_name_check")),
        sa.CheckConstraint("role in ('admin', 'teacher')", name=op.f("profiles_role_check")),
        sa.CheckConstraint(
            "status in ('invited', 'active', 'disabled')",
            name=op.f("profiles_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["id"],
            ["auth.users.id"],
            name=op.f("profiles_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("profiles_pkey")),
    )
    op.create_index(
        "profiles_single_admin_idx",
        "profiles",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'admin'"),
    )

    op.create_table(
        "provider_configs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary(), nullable=True),
        sa.Column("api_key_nonce", sa.LargeBinary(), nullable=True),
        sa.Column(
            "allowed_models",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column(
            "timeout_seconds",
            sa.Numeric(precision=8, scale=3),
            server_default=sa.text("'60'"),
            nullable=False,
        ),
        sa.Column("max_concurrency", sa.Integer(), server_default=sa.text("'1'"), nullable=False),
        sa.Column("monthly_budget", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_models) = 'array'",
            name=op.f("provider_configs_allowed_models_check"),
        ),
        sa.CheckConstraint(
            "provider_type in ('deepseek', 'kimi', 'glm', 'openai', 'anthropic', "
            "'gemini', 'openai_compatible')",
            name=op.f("provider_configs_provider_type_check"),
        ),
        sa.CheckConstraint(
            "status <> 'enabled' or (tested_at is not null and encrypted_api_key is not null "
            "and default_model is not null)",
            name=op.f("provider_configs_enabled_check"),
        ),
        sa.CheckConstraint(
            "status in ('draft', 'enabled', 'disabled')",
            name=op.f("provider_configs_status_check"),
        ),
        sa.CheckConstraint(
            "(encrypted_api_key is null) = (api_key_nonce is null)",
            name=op.f("provider_configs_key_material_check"),
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0 and max_concurrency > 0 "
            "and (monthly_budget is null or monthly_budget >= 0)",
            name=op.f("provider_configs_limits_check"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("provider_configs_pkey")),
        sa.UniqueConstraint("name", name=op.f("provider_configs_name_key")),
    )

    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(title) <> ''", name=op.f("assignments_title_check")),
        sa.CheckConstraint(
            "status in ('draft', 'ready', 'archived')",
            name=op.f("assignments_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("assignments_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("assignments_pkey")),
        sa.UniqueConstraint("id", "owner_id", name=op.f("assignments_id_owner_id_key")),
    )
    op.create_index(
        "assignments_owner_status_created_idx",
        "assignments",
        ["owner_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(action) <> '' and btrim(resource_type) <> ''",
            name=op.f("audit_logs_resource_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name=op.f("audit_logs_metadata_check"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["profiles.id"],
            name=op.f("audit_logs_actor_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("audit_logs_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("audit_logs_pkey")),
    )
    op.create_index(
        "audit_logs_actor_created_idx",
        "audit_logs",
        ["actor_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "audit_logs_owner_created_idx",
        "audit_logs",
        ["owner_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "audit_logs_resource_created_idx",
        "audit_logs",
        ["resource_type", "resource_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "rubric_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("original_rubric", sa.Text(), nullable=False),
        sa.Column("structured_rubric", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("total_score", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("score_step", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'draft' and confirmed_at is null) or "
            "(status in ('confirmed', 'superseded') and confirmed_at is not null "
            "and structured_rubric is not null)",
            name=op.f("rubric_versions_confirmation_check"),
        ),
        sa.CheckConstraint(
            "btrim(original_rubric) <> ''",
            name=op.f("rubric_versions_original_rubric_check"),
        ),
        sa.CheckConstraint(
            "structured_rubric is null or jsonb_typeof(structured_rubric) = 'object'",
            name=op.f("rubric_versions_structured_rubric_check"),
        ),
        sa.CheckConstraint(
            "status in ('draft', 'confirmed', 'superseded')",
            name=op.f("rubric_versions_status_check"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("rubric_versions_version_check")),
        sa.CheckConstraint(
            "total_score > 0 and score_step > 0 and score_step <= total_score "
            "and mod(total_score, score_step) = 0",
            name=op.f("rubric_versions_score_range_check"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            name=op.f("rubric_versions_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("rubric_versions_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("rubric_versions_pkey")),
        sa.UniqueConstraint(
            "assignment_id",
            "version",
            name=op.f("rubric_versions_assignment_id_version_key"),
        ),
        sa.UniqueConstraint(
            "id",
            "assignment_id",
            "owner_id",
            name=op.f("rubric_versions_id_assignment_id_owner_id_key"),
        ),
    )
    op.create_index(
        "rubric_versions_assignment_owner_idx",
        "rubric_versions",
        ["assignment_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "rubric_versions_owner_status_created_idx",
        "rubric_versions",
        ["owner_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "submissions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.LargeBinary(length=32), nullable=False),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("extracted_object_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'uploaded'"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0 and octet_length(content_sha256) = 32 "
            "and btrim(source_object_key) <> ''",
            name=op.f("submissions_file_check"),
        ),
        sa.CheckConstraint(
            "media_type in ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
            name=op.f("submissions_media_type_check"),
        ),
        sa.CheckConstraint(
            "status <> 'ready' or extracted_object_key is not null",
            name=op.f("submissions_ready_check"),
        ),
        sa.CheckConstraint(
            "status in ('uploaded', 'parsing', 'ready', 'failed')",
            name=op.f("submissions_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            name=op.f("submissions_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("submissions_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("submissions_pkey")),
        sa.UniqueConstraint(
            "assignment_id",
            "content_sha256",
            name=op.f("submissions_assignment_id_content_sha256_key"),
        ),
        sa.UniqueConstraint(
            "id",
            "assignment_id",
            "owner_id",
            name=op.f("submissions_id_assignment_id_owner_id_key"),
        ),
    )
    op.create_index(
        "submissions_assignment_owner_idx",
        "submissions",
        ["assignment_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "submissions_owner_status_created_idx",
        "submissions",
        ["owner_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "grading_jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("rubric_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider_config_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "model_parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'queued' and started_at is null and finished_at is null) or "
            "(status in ('running', 'paused', 'needs_review') and started_at is not null "
            "and finished_at is null) or "
            "(status in ('completed', 'failed', 'cancelled') and finished_at is not null)",
            name=op.f("grading_jobs_timestamps_check"),
        ),
        sa.CheckConstraint(
            "btrim(model) <> '' and btrim(prompt_version) <> '' "
            "and octet_length(prompt_hash) = 32 and btrim(idempotency_key) <> ''",
            name=op.f("grading_jobs_snapshot_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(model_parameters) = 'object'",
            name=op.f("grading_jobs_model_parameters_check"),
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'paused', 'needs_review', 'completed', "
            "'failed', 'cancelled')",
            name=op.f("grading_jobs_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            name=op.f("grading_jobs_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("grading_jobs_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_config_id"],
            ["provider_configs.id"],
            name=op.f("grading_jobs_provider_config_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rubric_version_id", "assignment_id", "owner_id"],
            [
                "rubric_versions.id",
                "rubric_versions.assignment_id",
                "rubric_versions.owner_id",
            ],
            name=op.f("grading_jobs_rubric_version_id_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("grading_jobs_pkey")),
        sa.UniqueConstraint(
            "id",
            "assignment_id",
            "owner_id",
            name=op.f("grading_jobs_id_assignment_id_owner_id_key"),
        ),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name=op.f("grading_jobs_owner_id_idempotency_key_key"),
        ),
    )
    op.create_index(
        "grading_jobs_assignment_owner_idx",
        "grading_jobs",
        ["assignment_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "grading_jobs_owner_status_created_idx",
        "grading_jobs",
        ["owner_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "grading_jobs_provider_config_idx",
        "grading_jobs",
        ["provider_config_id"],
        unique=False,
    )
    op.create_index(
        "grading_jobs_rubric_assignment_owner_idx",
        "grading_jobs",
        ["rubric_version_id", "assignment_id", "owner_id"],
        unique=False,
    )

    op.create_table(
        "exports",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("grading_job_id", sa.Uuid(), nullable=False),
        sa.Column("export_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column(
            "audit_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(idempotency_key) <> '' and "
            "((status = 'completed' and object_key is not null and finished_at is not null) or "
            "(status = 'failed' and error_code is not null and finished_at is not null) or "
            "(status in ('queued', 'running') and finished_at is null))",
            name=op.f("exports_result_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(audit_metadata) = 'object'",
            name=op.f("exports_audit_metadata_check"),
        ),
        sa.CheckConstraint(
            "export_type in ('draft', 'final')", name=op.f("exports_export_type_check")
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'completed', 'failed')",
            name=op.f("exports_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            name=op.f("exports_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["grading_job_id", "assignment_id", "owner_id"],
            ["grading_jobs.id", "grading_jobs.assignment_id", "grading_jobs.owner_id"],
            name=op.f("exports_grading_job_id_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("exports_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("exports_pkey")),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name=op.f("exports_owner_id_idempotency_key_key"),
        ),
    )
    op.create_index(
        "exports_assignment_owner_idx",
        "exports",
        ["assignment_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "exports_job_assignment_owner_idx",
        "exports",
        ["grading_job_id", "assignment_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "exports_owner_status_created_idx",
        "exports",
        ["owner_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "grading_job_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("grading_job_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('queued', 'running', 'needs_review', 'completed', 'failed', 'cancelled')",
            name=op.f("grading_job_items_status_check"),
        ),
        sa.CheckConstraint("position >= 0", name=op.f("grading_job_items_position_check")),
        sa.ForeignKeyConstraint(
            ["grading_job_id", "assignment_id", "owner_id"],
            ["grading_jobs.id", "grading_jobs.assignment_id", "grading_jobs.owner_id"],
            name=op.f("grading_job_items_grading_job_id_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("grading_job_items_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id", "assignment_id", "owner_id"],
            ["submissions.id", "submissions.assignment_id", "submissions.owner_id"],
            name=op.f("grading_job_items_submission_id_assignment_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("grading_job_items_pkey")),
        sa.UniqueConstraint(
            "grading_job_id",
            "position",
            name=op.f("grading_job_items_grading_job_id_position_key"),
        ),
        sa.UniqueConstraint(
            "grading_job_id",
            "submission_id",
            name=op.f("grading_job_items_grading_job_id_submission_id_key"),
        ),
        sa.UniqueConstraint("id", "owner_id", name=op.f("grading_job_items_id_owner_id_key")),
    )
    op.create_index(
        "grading_job_items_job_assignment_owner_idx",
        "grading_job_items",
        ["grading_job_id", "assignment_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "grading_job_items_job_status_position_idx",
        "grading_job_items",
        ["grading_job_id", "status", "position"],
        unique=False,
    )
    op.create_index(
        "grading_job_items_owner_status_created_idx",
        "grading_job_items",
        ["owner_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "grading_job_items_submission_assignment_owner_idx",
        "grading_job_items",
        ["submission_id", "assignment_id", "owner_id"],
        unique=False,
    )

    op.create_table(
        "grading_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("grading_job_item_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'running'"), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("max_score", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("total_score", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("criteria_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("overall_feedback", sa.Text(), nullable=True),
        sa.Column("raw_response_object_key", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'running' and finished_at is null) or "
            "(status in ('succeeded', 'needs_review') and finished_at is not null "
            "and total_score is not null and criteria_results is not null "
            "and overall_feedback is not null and raw_response_object_key is not null) or "
            "(status = 'failed' and finished_at is not null and error_code is not null)",
            name=op.f("grading_attempts_result_check"),
        ),
        sa.CheckConstraint(
            "octet_length(request_hash) = 32 and btrim(idempotency_key) <> ''",
            name=op.f("grading_attempts_request_check"),
        ),
        sa.CheckConstraint(
            "criteria_results is null or jsonb_typeof(criteria_results) = 'array'",
            name=op.f("grading_attempts_criteria_results_check"),
        ),
        sa.CheckConstraint(
            "status in ('running', 'succeeded', 'needs_review', 'failed')",
            name=op.f("grading_attempts_status_check"),
        ),
        sa.CheckConstraint(
            "attempt_number > 0", name=op.f("grading_attempts_attempt_number_check")
        ),
        sa.CheckConstraint(
            "max_score > 0 and (total_score is null or "
            "(total_score >= 0 and total_score <= max_score))",
            name=op.f("grading_attempts_score_range_check"),
        ),
        sa.ForeignKeyConstraint(
            ["grading_job_item_id", "owner_id"],
            ["grading_job_items.id", "grading_job_items.owner_id"],
            name=op.f("grading_attempts_grading_job_item_id_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("grading_attempts_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("grading_attempts_pkey")),
        sa.UniqueConstraint(
            "grading_job_item_id",
            "attempt_number",
            name=op.f("grading_attempts_grading_job_item_id_attempt_number_key"),
        ),
        sa.UniqueConstraint(
            "id",
            "grading_job_item_id",
            "owner_id",
            name=op.f("grading_attempts_id_grading_job_item_id_owner_id_key"),
        ),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name=op.f("grading_attempts_owner_id_idempotency_key_key"),
        ),
    )
    op.create_index(
        "grading_attempts_item_owner_idx",
        "grading_attempts",
        ["grading_job_item_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "grading_attempts_owner_status_created_idx",
        "grading_attempts",
        ["owner_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "teacher_reviews",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("grading_job_item_id", sa.Uuid(), nullable=False),
        sa.Column("grading_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("max_score", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("final_score", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("criteria_results", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'draft' and confirmed_at is null) or "
            "(status = 'confirmed' and confirmed_at is not null and final_score is not null "
            "and criteria_results is not null and feedback is not null)",
            name=op.f("teacher_reviews_confirmation_check"),
        ),
        sa.CheckConstraint(
            "(criteria_results is null or jsonb_typeof(criteria_results) = 'array') "
            "and jsonb_typeof(evidence) = 'array'",
            name=op.f("teacher_reviews_json_shapes_check"),
        ),
        sa.CheckConstraint(
            "status in ('draft', 'confirmed')",
            name=op.f("teacher_reviews_status_check"),
        ),
        sa.CheckConstraint(
            "revision_number > 0", name=op.f("teacher_reviews_revision_number_check")
        ),
        sa.CheckConstraint(
            "max_score > 0 and (final_score is null or "
            "(final_score >= 0 and final_score <= max_score))",
            name=op.f("teacher_reviews_score_range_check"),
        ),
        sa.ForeignKeyConstraint(
            ["grading_attempt_id", "grading_job_item_id", "owner_id"],
            [
                "grading_attempts.id",
                "grading_attempts.grading_job_item_id",
                "grading_attempts.owner_id",
            ],
            name="teacher_reviews_attempt_item_owner_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["profiles.id"],
            name=op.f("teacher_reviews_owner_id_fkey"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("teacher_reviews_pkey")),
        sa.UniqueConstraint(
            "grading_job_item_id",
            "revision_number",
            name=op.f("teacher_reviews_grading_job_item_id_revision_number_key"),
        ),
    )
    op.create_index(
        "teacher_reviews_attempt_item_owner_idx",
        "teacher_reviews",
        ["grading_attempt_id", "grading_job_item_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "teacher_reviews_item_owner_idx",
        "teacher_reviews",
        ["grading_job_item_id", "owner_id"],
        unique=False,
    )
    op.create_index(
        "teacher_reviews_one_confirmed_idx",
        "teacher_reviews",
        ["grading_job_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'confirmed'"),
    )
    op.create_index(
        "teacher_reviews_owner_status_created_idx",
        "teacher_reviews",
        ["owner_id", "status", "created_at"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in ("profiles", "provider_configs", "assignments"):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_set_updated_at
            BEFORE UPDATE ON public.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION public.paper_grading_set_updated_at()
            """
        )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_protect_rubric_history()
        RETURNS trigger
        LANGUAGE plpgsql
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
    op.execute(
        """
        CREATE TRIGGER rubric_versions_protect_history
        BEFORE UPDATE OR DELETE ON public.rubric_versions
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_protect_rubric_history()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_protect_job_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
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
                NEW.prompt_hash,
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
                OLD.prompt_hash,
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
    op.execute(
        """
        CREATE TRIGGER grading_jobs_protect_snapshot
        BEFORE UPDATE OR DELETE ON public.grading_jobs
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_protect_job_snapshot()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_reject_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit log history is immutable' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_reject_mutation
        BEFORE UPDATE OR DELETE ON public.audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_reject_history_mutation()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_protect_attempt_history()
        RETURNS trigger
        LANGUAGE plpgsql
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
                NEW.request_hash,
                NEW.idempotency_key,
                NEW.max_score,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.grading_job_item_id,
                OLD.attempt_number,
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
    op.execute(
        """
        CREATE TRIGGER grading_attempts_protect_history
        BEFORE UPDATE OR DELETE ON public.grading_attempts
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_protect_attempt_history()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_validate_attempt_score()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            rubric_total numeric(10, 4);
        BEGIN
            SELECT rubric.total_score
            INTO rubric_total
            FROM public.grading_job_items AS item
            JOIN public.grading_jobs AS job
              ON job.id = item.grading_job_id
             AND job.assignment_id = item.assignment_id
             AND job.owner_id = item.owner_id
            JOIN public.rubric_versions AS rubric
              ON rubric.id = job.rubric_version_id
             AND rubric.assignment_id = job.assignment_id
             AND rubric.owner_id = job.owner_id
            WHERE item.id = NEW.grading_job_item_id
              AND item.owner_id = NEW.owner_id;

            IF NOT FOUND OR NEW.max_score <> rubric_total THEN
                RAISE EXCEPTION 'attempt max_score must equal rubric total_score'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER grading_attempts_validate_rubric_score
        BEFORE INSERT OR UPDATE ON public.grading_attempts
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_validate_attempt_score()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_protect_review_history()
        RETURNS trigger
        LANGUAGE plpgsql
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
            IF ROW(
                NEW.id,
                NEW.owner_id,
                NEW.grading_job_item_id,
                NEW.grading_attempt_id,
                NEW.revision_number,
                NEW.max_score,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.owner_id,
                OLD.grading_job_item_id,
                OLD.grading_attempt_id,
                OLD.revision_number,
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
    op.execute(
        """
        CREATE TRIGGER teacher_reviews_protect_history
        BEFORE UPDATE OR DELETE ON public.teacher_reviews
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_protect_review_history()
        """
    )

    op.execute(
        """
        CREATE FUNCTION public.paper_grading_validate_review_score()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            attempt_max numeric(10, 4);
        BEGIN
            SELECT attempt.max_score
            INTO attempt_max
            FROM public.grading_attempts AS attempt
            WHERE attempt.id = NEW.grading_attempt_id
              AND attempt.grading_job_item_id = NEW.grading_job_item_id
              AND attempt.owner_id = NEW.owner_id;

            IF NOT FOUND OR NEW.max_score <> attempt_max THEN
                RAISE EXCEPTION 'review max_score must equal attempt max_score'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER teacher_reviews_validate_attempt_score
        BEFORE INSERT OR UPDATE ON public.teacher_reviews
        FOR EACH ROW
        EXECUTE FUNCTION public.paper_grading_validate_review_score()
        """
    )

    for table_name in (
        "profiles",
        "provider_configs",
        "assignments",
        "rubric_versions",
        "submissions",
        "grading_jobs",
        "grading_job_items",
        "grading_attempts",
        "teacher_reviews",
        "audit_logs",
        "exports",
    ):
        op.execute(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """按依赖关系逆序删除阶段 2 表。"""

    op.drop_table("teacher_reviews")
    op.drop_table("grading_attempts")
    op.drop_table("grading_job_items")
    op.drop_table("exports")
    op.drop_table("grading_jobs")
    op.drop_table("submissions")
    op.drop_table("rubric_versions")
    op.drop_table("audit_logs")
    op.drop_table("assignments")
    op.drop_table("provider_configs")
    op.drop_table("profiles")
    op.execute("DROP FUNCTION public.paper_grading_validate_review_score()")
    op.execute("DROP FUNCTION public.paper_grading_protect_review_history()")
    op.execute("DROP FUNCTION public.paper_grading_validate_attempt_score()")
    op.execute("DROP FUNCTION public.paper_grading_protect_attempt_history()")
    op.execute("DROP FUNCTION public.paper_grading_reject_history_mutation()")
    op.execute("DROP FUNCTION public.paper_grading_protect_job_snapshot()")
    op.execute("DROP FUNCTION public.paper_grading_protect_rubric_history()")
    op.execute("DROP FUNCTION public.paper_grading_set_updated_at()")
