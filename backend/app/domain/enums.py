"""数据库状态与角色的领域词汇。"""

from enum import StrEnum


class ProfileRole(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"


class ProfileStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"


class ProviderType(StrEnum):
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    GLM = "glm"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"


class ProviderStatus(StrEnum):
    DRAFT = "draft"
    ENABLED = "enabled"
    DISABLED = "disabled"


class AssignmentStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class RubricStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class SubmissionStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"


class GradingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GradingItemStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GradingAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class TeacherReviewStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class ExportType(StrEnum):
    DRAFT = "draft"
    FINAL = "final"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
