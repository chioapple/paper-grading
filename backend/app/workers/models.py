"""阶段十批次、单篇任务和进度的公共契约。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import ProviderType
from app.domain.grading import canonical_sha256
from app.providers.base import ProviderModelProfile

JobStatus = Literal[
    "queued",
    "running",
    "paused",
    "needs_review",
    "completed",
    "failed",
    "cancelled",
]
ItemStatus = Literal[
    "queued",
    "running",
    "needs_review",
    "completed",
    "failed",
    "cancelled",
]


class GradingJobCreate(BaseModel):
    """教师创建批次时唯一可控的输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    submission_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("幂等键不能为空")
        return normalized

    @model_validator(mode="after")
    def require_unique_submissions(self) -> Self:
        if len(set(self.submission_ids)) != len(self.submission_ids):
            raise ValueError("同一批次不得重复选择论文")
        return self

    def request_hash(self, assignment_id: UUID) -> bytes:
        """幂等键冲突时区分同一请求与不同请求。"""

        return canonical_sha256(
            {
                "assignment_id": assignment_id,
                "submission_ids": self.submission_ids,
            }
        )


class GradingProviderSnapshot(BaseModel):
    """批次保存的完整非密钥供应商执行快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_type: ProviderType
    base_url: str = Field(min_length=1, max_length=2048)
    timeout_seconds: Decimal = Field(gt=0, le=300, max_digits=8, decimal_places=3)
    max_concurrency: int = Field(ge=1, le=100)
    model_profile: ProviderModelProfile

    def snapshot_hash(self) -> bytes:
        return canonical_sha256(self)


class GradingJobItemView(BaseModel):
    """教师可见的单篇评分状态，不含论文正文或模型原始响应。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    submission_id: UUID
    position: int = Field(ge=0, le=99)
    status: ItemStatus
    dispatch_version: int = Field(default=1, gt=0)
    attempt_count: int = Field(ge=0)
    error_code: str | None


class GradingJobView(BaseModel):
    """由 PostgreSQL 状态汇总生成的批次完整安全投影。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    assignment_id: UUID
    rubric_version_id: UUID
    model: str
    status: JobStatus
    state_version: int = Field(gt=0)
    total: int = Field(ge=1, le=100)
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    items: tuple[GradingJobItemView, ...] = Field(min_length=1, max_length=100)
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        counts = (
            self.queued
            + self.running
            + self.needs_review
            + self.completed
            + self.failed
            + self.cancelled
        )
        if counts != self.total or len(self.items) != self.total:
            raise ValueError("批次状态计数必须覆盖全部论文")
        return self


class GradingJobCreation(BaseModel):
    """仓库原子创建或命中同一幂等请求的结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job: GradingJobView
    created: bool
