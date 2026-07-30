"""阶段 2 的 PostgreSQL 持久化模型。"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.enums import (
    AssignmentStatus,
    ExportStatus,
    ExportType,
    GradingAttemptStatus,
    GradingItemStatus,
    GradingJobStatus,
    ProfileRole,
    ProfileStatus,
    ProviderStatus,
    ProviderType,
    RubricStatus,
    SubmissionStatus,
    TeacherReviewStatus,
)

NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """所有持久化模型共享的元数据。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


auth_users = Table(
    "users",
    Base.metadata,
    Column("id", Uuid, primary_key=True),
    schema="auth",
    info={"external": True},
)


def enum_check(column: str, values: type[StrEnum], name: str) -> CheckConstraint:
    """为文本状态字段生成明确的允许值约束。"""

    allowed = ", ".join(f"'{item.value}'" for item in values)
    return CheckConstraint(f"{column} in ({allowed})", name=name)


class Profile(Base):
    """Supabase Auth 用户对应的系统角色与账户状态。"""

    __tablename__ = "profiles"
    __table_args__ = (
        enum_check("role", ProfileRole, "role"),
        enum_check("status", ProfileStatus, "status"),
        CheckConstraint("btrim(display_name) <> ''", name="display_name"),
        Index(
            "profiles_single_admin_idx",
            "role",
            unique=True,
            postgresql_where=text("role = 'admin'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'invited'"))
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderConfig(Base):
    """管理员维护的模型供应商配置。"""

    __tablename__ = "provider_configs"
    __table_args__ = (
        enum_check("provider_type", ProviderType, "provider_type"),
        enum_check("status", ProviderStatus, "status"),
        CheckConstraint(
            "timeout_seconds > 0 and max_concurrency > 0 "
            "and (monthly_budget is null or monthly_budget >= 0)",
            name="limits",
        ),
        CheckConstraint(
            "(encrypted_api_key is null and api_key_nonce is null) or "
            "(encrypted_api_key is not null and api_key_nonce is not null "
            "and octet_length(api_key_nonce) = 12 and octet_length(encrypted_api_key) >= 17)",
            name="key_material",
        ),
        CheckConstraint(
            "status <> 'enabled' or "
            "(tested_at is not null and encrypted_api_key is not null "
            "and default_model is not null and tested_config_version = config_version)",
            name="enabled",
        ),
        CheckConstraint(
            "config_version > 0 and (tested_config_version is null or tested_config_version > 0) "
            "and ((tested_at is null) = (tested_config_version is null))",
            name="test_version",
        ),
        CheckConstraint("btrim(name) <> '' and btrim(base_url) <> ''", name="text"),
        CheckConstraint(
            "default_model is null or (btrim(default_model) <> '' "
            "and allowed_models @> jsonb_build_array(default_model))",
            name="default_model",
        ),
        CheckConstraint("jsonb_typeof(allowed_models) = 'array'", name="allowed_models"),
        CheckConstraint("jsonb_typeof(model_profiles) = 'object'", name="model_profiles"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    api_key_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    allowed_models: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    default_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[Decimal] = mapped_column(
        Numeric(8, 3), nullable=False, server_default=text("'60'")
    )
    max_concurrency: Mapped[int] = mapped_column(nullable=False, server_default=text("'1'"))
    monthly_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    model_profiles: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    config_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("'1'")
    )
    tested_config_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Assignment(Base):
    """教师创建的作文作业。"""

    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        enum_check("status", AssignmentStatus, "status"),
        CheckConstraint("btrim(title) <> ''", name="title"),
        CheckConstraint("btrim(instructions) <> ''", name="instructions"),
        Index("assignments_owner_status_created_idx", "owner_id", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RubricVersion(Base):
    """作业评分标准的不可覆盖版本。"""

    __tablename__ = "rubric_versions"
    __table_args__ = (
        UniqueConstraint("id", "assignment_id", "owner_id"),
        UniqueConstraint("assignment_id", "version"),
        ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            ondelete="RESTRICT",
        ),
        enum_check("status", RubricStatus, "status"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(
            "total_score > 0 and score_step > 0 and score_step <= total_score "
            "and mod(total_score, score_step) = 0",
            name="score_range",
        ),
        CheckConstraint(
            "(status = 'draft' and confirmed_at is null) or "
            "(status in ('confirmed', 'superseded') and confirmed_at is not null "
            "and structured_rubric is not null and provider_config_id is not null "
            "and btrim(model) <> '')",
            name="confirmation",
        ),
        CheckConstraint(
            "structured_rubric is null or jsonb_typeof(structured_rubric) = 'object'",
            name="structured_rubric",
        ),
        CheckConstraint("btrim(original_rubric) <> ''", name="original_rubric"),
        CheckConstraint(
            "((provider_config_id is null and model is null) or "
            "(provider_config_id is not null and btrim(model) <> '')) "
            "and (structured_rubric is null or provider_config_id is not null)",
            name="generation",
        ),
        CheckConstraint(
            "structured_rubric is null or "
            "public.paper_grading_valid_structured_rubric("
            "structured_rubric, total_score, score_step)",
            name="content",
        ),
        Index("rubric_versions_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index("rubric_versions_assignment_owner_idx", "assignment_id", "owner_id"),
        Index("rubric_versions_provider_config_id_idx", "provider_config_id"),
        Index(
            "rubric_versions_one_draft_idx",
            "assignment_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        Index(
            "rubric_versions_one_confirmed_idx",
            "assignment_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    provider_config_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("provider_configs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    original_rubric: Mapped[str] = mapped_column(Text, nullable=False)
    structured_rubric: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    total_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    score_step: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Submission(Base):
    """论文文件元数据；正文和提取文本只存 Supabase Storage。"""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("id", "assignment_id", "owner_id"),
        UniqueConstraint("assignment_id", "content_sha256"),
        UniqueConstraint("source_object_key"),
        ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            ondelete="RESTRICT",
        ),
        enum_check("status", SubmissionStatus, "status"),
        CheckConstraint(
            "media_type in ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
            name="media_type",
        ),
        CheckConstraint(
            "file_size_bytes > 0 and file_size_bytes <= 20971520 "
            "and octet_length(content_sha256) = 32 "
            "and btrim(source_object_key) <> ''",
            name="file",
        ),
        CheckConstraint(
            "char_length(original_filename) between 1 and 255 and btrim(original_filename) <> ''",
            name="original_filename",
        ),
        CheckConstraint(
            "(status in ('uploaded', 'parsing') and extracted_object_key is null "
            "and error_code is null) or "
            "(status = 'ready' and extracted_object_key is not null and error_code is null) or "
            "(status = 'failed' and extracted_object_key is null "
            "and error_code is not null and btrim(error_code) <> '')",
            name="state",
        ),
        CheckConstraint(
            "source_object_key = 'teachers/' || owner_id::text || "
            "'/assignments/' || assignment_id::text || '/submissions/' || id::text || "
            "case when media_type = 'application/pdf' then '/source.pdf' "
            "else '/source.docx' end "
            "and (extracted_object_key is null or extracted_object_key = "
            "'teachers/' || owner_id::text || '/assignments/' || assignment_id::text || "
            "'/submissions/' || id::text || '/document-blocks.v1.json')",
            name="object_keys",
        ),
        Index("submissions_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index("submissions_assignment_owner_idx", "assignment_id", "owner_id"),
        Index(
            "submissions_extracted_object_key_idx",
            "extracted_object_key",
            unique=True,
            postgresql_where=text("extracted_object_key is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_sha256: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    source_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'uploaded'"))
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GradingJob(Base):
    """固定模型、参数、Rubric 和提示词版本的批改批次。"""

    __tablename__ = "grading_jobs"
    __table_args__ = (
        UniqueConstraint("id", "assignment_id", "owner_id"),
        UniqueConstraint("owner_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rubric_version_id", "assignment_id", "owner_id"],
            ["rubric_versions.id", "rubric_versions.assignment_id", "rubric_versions.owner_id"],
            ondelete="RESTRICT",
        ),
        enum_check("status", GradingJobStatus, "status"),
        CheckConstraint(
            "provider_config_version > 0 and btrim(model) <> '' "
            "and jsonb_typeof(result_schema) = 'object' "
            "and octet_length(request_hash) = 32 "
            "and octet_length(model_parameters_hash) = 32 "
            "and btrim(prompt_version) <> '' "
            "and octet_length(prompt_hash) = 32 "
            "and btrim(result_schema_version) <> '' "
            "and octet_length(result_schema_hash) = 32 "
            "and octet_length(rubric_hash) = 32 "
            "and btrim(idempotency_key) <> ''",
            name="snapshot",
        ),
        CheckConstraint(
            "expected_item_count between 1 and 100 and state_version > 0",
            name="progress",
        ),
        CheckConstraint(
            "btrim(assignment_title_snapshot) <> '' "
            "and btrim(assignment_instructions_snapshot) <> ''",
            name="assignment_snapshot",
        ),
        CheckConstraint(
            "jsonb_typeof(model_parameters) = 'object'",
            name="model_parameters",
        ),
        CheckConstraint(
            "(status = 'queued' and started_at is null and finished_at is null) or "
            "(status in ('running', 'paused', 'needs_review') and started_at is not null "
            "and finished_at is null) or "
            "(status in ('completed', 'failed', 'cancelled') and finished_at is not null)",
            name="timestamps",
        ),
        Index("grading_jobs_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index("grading_jobs_assignment_owner_idx", "assignment_id", "owner_id"),
        Index(
            "grading_jobs_rubric_assignment_owner_idx",
            "rubric_version_id",
            "assignment_id",
            "owner_id",
        ),
        Index("grading_jobs_provider_config_idx", "provider_config_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    rubric_version_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    provider_config_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("provider_configs.id", ondelete="RESTRICT"), nullable=False
    )
    provider_config_version: Mapped[int] = mapped_column(nullable=False)
    assignment_title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    assignment_instructions_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    expected_item_count: Mapped[int] = mapped_column(nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_parameters: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    model_parameters_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    result_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    result_schema: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result_schema_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    rubric_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("'1'")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GradingJobItem(Base):
    """批改批次中的单篇论文任务。"""

    __tablename__ = "grading_job_items"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        UniqueConstraint("grading_job_id", "submission_id"),
        UniqueConstraint("grading_job_id", "position"),
        ForeignKeyConstraint(
            ["grading_job_id", "assignment_id", "owner_id"],
            ["grading_jobs.id", "grading_jobs.assignment_id", "grading_jobs.owner_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["submission_id", "assignment_id", "owner_id"],
            ["submissions.id", "submissions.assignment_id", "submissions.owner_id"],
            ondelete="RESTRICT",
        ),
        enum_check("status", GradingItemStatus, "status"),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint("dispatch_version > 0 and retry_count >= 0", name="delivery"),
        CheckConstraint(
            "(status = 'queued' and finished_at is null and lease_token is null "
            "and lease_expires_at is null and error_code is null) or "
            "(status = 'running' and started_at is not null and finished_at is null "
            "and lease_token is not null and lease_expires_at is not null "
            "and error_code is null) or "
            "(status = 'needs_review' and finished_at is not null "
            "and lease_token is null and lease_expires_at is null "
            "and (error_code is null or btrim(error_code) <> '')) or "
            "(status = 'completed' and finished_at is not null "
            "and lease_token is null and lease_expires_at is null and error_code is null) or "
            "(status = 'failed' and finished_at is not null and lease_token is null "
            "and lease_expires_at is null and btrim(error_code) <> '') or "
            "(status = 'cancelled' and finished_at is not null and lease_token is null "
            "and lease_expires_at is null)",
            name="state",
        ),
        Index("grading_job_items_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index(
            "grading_job_items_job_assignment_owner_idx",
            "grading_job_id",
            "assignment_id",
            "owner_id",
        ),
        Index(
            "grading_job_items_submission_assignment_owner_idx",
            "submission_id",
            "assignment_id",
            "owner_id",
        ),
        Index("grading_job_items_job_status_position_idx", "grading_job_id", "status", "position"),
        Index(
            "grading_job_items_dispatch_idx",
            "available_at",
            "created_at",
            "id",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "grading_job_items_expired_lease_idx",
            "lease_expires_at",
            "id",
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grading_job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    submission_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    position: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    dispatch_version: Mapped[int] = mapped_column(nullable=False, server_default=text("'1'"))
    retry_count: Mapped[int] = mapped_column(nullable=False, server_default=text("'0'"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GradingAttempt(Base):
    """单篇论文一次不可覆盖的模型调用结果。"""

    __tablename__ = "grading_attempts"
    __table_args__ = (
        UniqueConstraint("id", "grading_job_item_id", "owner_id"),
        UniqueConstraint("grading_job_item_id", "attempt_number"),
        UniqueConstraint("grading_job_item_id", "scoring_round", "call_sequence"),
        UniqueConstraint("owner_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["grading_job_item_id", "owner_id"],
            ["grading_job_items.id", "grading_job_items.owner_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["parent_attempt_id", "grading_job_item_id", "owner_id"],
            [
                "grading_attempts.id",
                "grading_attempts.grading_job_item_id",
                "grading_attempts.owner_id",
            ],
            ondelete="RESTRICT",
            name="grading_attempts_parent_item_owner_fkey",
        ),
        enum_check("status", GradingAttemptStatus, "status"),
        CheckConstraint("attempt_number > 0", name="attempt_number"),
        CheckConstraint("scoring_round > 0 and call_sequence > 0", name="call_position"),
        CheckConstraint(
            "attempt_kind in ('initial', 'correction', 'automatic_retry', 'manual_retry')",
            name="attempt_kind",
        ),
        CheckConstraint(
            "provider_call_state in ('started', 'not_sent', 'response_received', 'ambiguous')",
            name="provider_call_state",
        ),
        CheckConstraint(
            "max_score > 0 and (total_score is null or "
            "(total_score >= 0 and total_score <= max_score))",
            name="score_range",
        ),
        CheckConstraint(
            "btrim(request_version) <> '' and octet_length(request_hash) = 32 "
            "and btrim(idempotency_key) <> ''",
            name="request",
        ),
        CheckConstraint(
            "criteria_results is null or jsonb_typeof(criteria_results) = 'array'",
            name="criteria_results",
        ),
        CheckConstraint(
            "deduction_results is null or jsonb_typeof(deduction_results) = 'array'",
            name="deduction_results",
        ),
        CheckConstraint(
            "error_details is null or jsonb_typeof(error_details) = 'object'",
            name="error_details",
        ),
        CheckConstraint(
            "(input_tokens is null and cached_input_tokens is null "
            "and cache_write_input_tokens is null and output_tokens is null "
            "and reasoning_tokens is null and total_tokens is null) or "
            "(input_tokens >= 0 and cached_input_tokens >= 0 "
            "and cache_write_input_tokens >= 0 and output_tokens >= 0 "
            "and reasoning_tokens >= 0 and (total_tokens is null or total_tokens >= 0) "
            "and cached_input_tokens + cache_write_input_tokens <= input_tokens "
            "and reasoning_tokens <= output_tokens)",
            name="token_usage",
        ),
        CheckConstraint(
            "(estimated_cost_amount is null and cost_currency is null and tariff_version is null) "
            "or (estimated_cost_amount >= 0 and cost_currency ~ '^[A-Z]{3}$' "
            "and btrim(tariff_version) <> '')",
            name="cost",
        ),
        CheckConstraint(
            "((raw_response_object_key is null) = (raw_response_sha256 is null)) "
            "and (raw_response_sha256 is null or octet_length(raw_response_sha256) = 32)",
            name="raw_response",
        ),
        CheckConstraint(
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
            name="result",
        ),
        Index("grading_attempts_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index("grading_attempts_item_owner_idx", "grading_job_item_id", "owner_id"),
        Index(
            "grading_attempts_parent_item_owner_idx",
            "parent_attempt_id",
            "grading_job_item_id",
            "owner_id",
        ),
        Index(
            "grading_attempts_one_running_idx",
            "grading_job_item_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index(
            "grading_attempts_raw_response_object_key_idx",
            "raw_response_object_key",
            unique=True,
            postgresql_where=text("raw_response_object_key is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    grading_job_item_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    parent_attempt_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    scoring_round: Mapped[int] = mapped_column(nullable=False)
    call_sequence: Mapped[int] = mapped_column(nullable=False)
    attempt_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    provider_call_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider_call_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'started'")
    )
    request_version: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    deduction_total: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    criteria_results: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    deduction_results: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    overall_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_write_input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estimated_cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 9), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    tariff_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, object] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TeacherReview(Base):
    """教师对模型结果的独立复核版本。"""

    __tablename__ = "teacher_reviews"
    __table_args__ = (
        UniqueConstraint("grading_job_item_id", "revision_number"),
        ForeignKeyConstraint(
            ["grading_attempt_id", "grading_job_item_id", "owner_id"],
            [
                "grading_attempts.id",
                "grading_attempts.grading_job_item_id",
                "grading_attempts.owner_id",
            ],
            ondelete="RESTRICT",
            name="teacher_reviews_attempt_item_owner_fkey",
        ),
        enum_check("status", TeacherReviewStatus, "status"),
        CheckConstraint("revision_number > 0", name="revision_number"),
        CheckConstraint(
            "max_score > 0 and final_score >= 0 and final_score <= max_score",
            name="score_range",
        ),
        CheckConstraint(
            "(status = 'draft' and confirmed_at is null) or "
            "(status = 'confirmed' and confirmed_at is not null)",
            name="confirmation",
        ),
        CheckConstraint(
            "jsonb_typeof(criteria_results) = 'array' "
            "and jsonb_typeof(deduction_results) = 'array' "
            "and jsonb_typeof(evidence) = 'array'",
            name="json_shapes",
        ),
        CheckConstraint(
            "subtotal >= 0 and deduction_total >= 0 "
            "and final_score = greatest(0, subtotal - deduction_total)",
            name="totals",
        ),
        Index("teacher_reviews_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index(
            "teacher_reviews_attempt_item_owner_idx",
            "grading_attempt_id",
            "grading_job_item_id",
            "owner_id",
        ),
        Index("teacher_reviews_item_owner_idx", "grading_job_item_id", "owner_id"),
        Index("teacher_reviews_one_attempt_idx", "grading_attempt_id", unique=True),
        Index(
            "teacher_reviews_one_confirmed_idx",
            "grading_job_item_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    grading_job_item_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grading_attempt_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    max_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    deduction_total: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    final_score: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    criteria_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    deduction_results: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    feedback: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base):
    """只追加的操作审计元数据。"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "btrim(action) <> '' and btrim(resource_type) <> ''",
            name="resource",
        ),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata"),
        Index("audit_logs_owner_created_idx", "owner_id", "created_at"),
        Index("audit_logs_actor_created_idx", "actor_id", "created_at"),
        Index("audit_logs_resource_created_idx", "resource_type", "resource_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    request_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Export(Base):
    """Excel 导出文件和审计快照元数据。"""

    __tablename__ = "exports"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "grading_job_id"),
        UniqueConstraint("owner_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["assignment_id", "owner_id"],
            ["assignments.id", "assignments.owner_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["grading_job_id", "assignment_id", "owner_id"],
            ["grading_jobs.id", "grading_jobs.assignment_id", "grading_jobs.owner_id"],
            ondelete="RESTRICT",
        ),
        enum_check("export_type", ExportType, "export_type"),
        enum_check("status", ExportStatus, "status"),
        CheckConstraint(
            "btrim(idempotency_key) <> '' and octet_length(request_hash) = 32 "
            "and btrim(workbook_schema_version) <> '' "
            "and jsonb_typeof(audit_metadata) = 'object'",
            name="request_snapshot",
        ),
        CheckConstraint(
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
            name="result",
        ),
        CheckConstraint(
            "object_key is null or object_key = 'exports/' || id::text || '/workbook.xlsx'",
            name="object_key",
        ),
        CheckConstraint(
            "safe_filename is null or (char_length(safe_filename) between 6 and 255 "
            "and safe_filename like '%.xlsx' and safe_filename !~ '[/\\\\]')",
            name="safe_filename",
        ),
        Index("exports_owner_status_created_idx", "owner_id", "status", "created_at"),
        Index("exports_assignment_owner_idx", "assignment_id", "owner_id"),
        Index(
            "exports_job_assignment_owner_idx",
            "grading_job_id",
            "assignment_id",
            "owner_id",
        ),
        Index(
            "exports_dispatch_idx",
            "status",
            "lease_expires_at",
            "created_at",
            postgresql_where=text("status in ('queued', 'running')"),
        ),
        Index(
            "exports_object_key_idx",
            "object_key",
            unique=True,
            postgresql_where=text("object_key is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grading_job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    export_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    workbook_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExportItem(Base):
    """导出创建时冻结的单篇结果，不由 Worker 回读实时评分表补字段。"""

    __tablename__ = "export_items"
    __table_args__ = (
        UniqueConstraint("export_id", "position"),
        UniqueConstraint("export_id", "grading_job_item_id"),
        ForeignKeyConstraint(
            ["export_id", "owner_id", "grading_job_id"],
            ["exports.id", "exports.owner_id", "exports.grading_job_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["grading_job_item_id", "owner_id"],
            ["grading_job_items.id", "grading_job_items.owner_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["submission_id", "assignment_id", "owner_id"],
            ["submissions.id", "submissions.assignment_id", "submissions.owner_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["grading_attempt_id", "grading_job_item_id", "owner_id"],
            [
                "grading_attempts.id",
                "grading_attempts.grading_job_item_id",
                "grading_attempts.owner_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["teacher_review_id"],
            ["teacher_reviews.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 0", name="position"),
        CheckConstraint(
            "source_type in ('ai_suggestion', 'teacher_draft', 'teacher_confirmed')",
            name="source_type",
        ),
        CheckConstraint(
            "(source_type = 'ai_suggestion' and teacher_review_id is null "
            "and review_revision is null) or "
            "(source_type in ('teacher_draft', 'teacher_confirmed') "
            "and teacher_review_id is not null and review_revision > 0)",
            name="review_source",
        ),
        CheckConstraint(
            "char_length(original_filename) between 1 and 255 and btrim(original_filename) <> ''",
            name="original_filename",
        ),
        CheckConstraint(
            "jsonb_typeof(result_snapshot) = 'object' "
            "and result_snapshot ->> 'schema_version' = 'export-item-snapshot.v1'",
            name="result_snapshot",
        ),
        Index("export_items_owner_created_idx", "owner_id", "created_at"),
        Index("export_items_export_position_idx", "export_id", "position"),
        Index(
            "export_items_export_owner_job_idx",
            "export_id",
            "owner_id",
            "grading_job_id",
        ),
        Index("export_items_job_owner_idx", "grading_job_id", "owner_id"),
        Index("export_items_item_owner_idx", "grading_job_item_id", "owner_id"),
        Index(
            "export_items_submission_assignment_owner_idx",
            "submission_id",
            "assignment_id",
            "owner_id",
        ),
        Index(
            "export_items_attempt_item_owner_idx",
            "grading_attempt_id",
            "grading_job_item_id",
            "owner_id",
        ),
        Index("export_items_review_idx", "teacher_review_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    export_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("profiles.id", ondelete="RESTRICT"), nullable=False
    )
    assignment_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grading_job_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grading_job_item_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    submission_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grading_attempt_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    teacher_review_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    review_revision: Mapped[int | None] = mapped_column(nullable=True)
    position: Mapped[int] = mapped_column(nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    result_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
