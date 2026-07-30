"""阶段十一教师复核的安全公共契约。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.grading import (
    DeductionResult,
    DimensionResult,
    ModelDecimal,
    require_english_narrative,
)
from app.domain.rubric import StructuredRubric
from app.parsing.models import ParsedDocument

ReviewItemStatus = Literal[
    "queued",
    "running",
    "needs_review",
    "completed",
    "failed",
    "cancelled",
]
ReviewJobStatus = Literal[
    "queued",
    "running",
    "paused",
    "needs_review",
    "completed",
    "failed",
    "cancelled",
]


class ReviewQueueItem(BaseModel):
    """教师批次队列中的可读论文行。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    submission_id: UUID
    original_filename: str = Field(min_length=1, max_length=255)
    position: int = Field(ge=0, le=99)
    status: ReviewItemStatus
    attempt_count: int = Field(ge=0)
    error_code: str | None = None
    review_available: bool
    review_id: UUID | None
    review_revision: int | None = Field(default=None, gt=0)
    review_status: Literal["draft", "confirmed"] | None

    @model_validator(mode="after")
    def require_complete_review_pointer(self) -> Self:
        values = (self.review_id, self.review_revision, self.review_status)
        if any(value is None for value in values) and not all(value is None for value in values):
            raise ValueError("复核指针必须完整或全部为空")
        return self


class ReviewRegradeTarget(BaseModel):
    """重评门禁只需要归属、状态和已确认复核，不依赖成功 attempt。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    item_id: UUID
    item_status: ReviewItemStatus
    has_confirmed_review: bool


class ReviewJobSummary(BaseModel):
    """工作台列表所需的批次和论文状态，不暴露执行元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    assignment_id: UUID
    assignment_title: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=300)
    status: ReviewJobStatus
    total: int = Field(ge=1, le=100)
    needs_review: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    items: tuple[ReviewQueueItem, ...] = Field(min_length=1, max_length=100)
    created_at: datetime
    finished_at: datetime | None

    @model_validator(mode="after")
    def require_complete_queue(self) -> Self:
        if len(self.items) != self.total:
            raise ValueError("工作台批次必须返回全部论文")
        return self


class ReviewCriterionInput(BaseModel):
    """教师对一个评分维度的独立判断；证据单独保存。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    score: ModelDecimal
    reason: str = Field(min_length=1, max_length=10_000)
    revision_suggestions: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return require_english_narrative(value, "评分理由")

    @field_validator("revision_suggestions")
    @classmethod
    def validate_suggestions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("修改建议不能为空")
        for value in normalized:
            require_english_narrative(value, "修改建议")
        return normalized


class ReviewDeductionInput(BaseModel):
    """教师只判断 Rubric 固定扣分是否适用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    deduction_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    applied: bool
    reason: str = Field(min_length=1, max_length=10_000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return require_english_narrative(value, "扣分理由")


class ReviewEvidenceInput(BaseModel):
    """明确绑定维度或扣分项的单文本块逐字证据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: Literal["dimension", "deduction"]
    target_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    block_id: str = Field(pattern=r"^b[0-9]{6}$")
    quote: str = Field(min_length=1, max_length=20_000)

    @field_validator("quote")
    @classmethod
    def preserve_verbatim_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("证据原文不能为空")
        return value


class ReviewDraftInput(BaseModel):
    """浏览器可提交的完整复核草稿；故意不接受总分。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: UUID
    criteria: tuple[ReviewCriterionInput, ...] = Field(min_length=1, max_length=100)
    deductions: tuple[ReviewDeductionInput, ...] = Field(max_length=100)
    evidence: tuple[ReviewEvidenceInput, ...] = Field(max_length=10_000)
    overall_feedback: str = Field(min_length=1, max_length=20_000)
    change_reason: str | None = Field(default=None, max_length=4000)

    @field_validator("overall_feedback", mode="before")
    @classmethod
    def normalize_feedback(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return require_english_narrative(value, "总体反馈")

    @field_validator("change_reason", mode="before")
    @classmethod
    def normalize_change_reason(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip() or None
        return value

    @model_validator(mode="after")
    def require_unique_ids(self) -> Self:
        criterion_ids = [criterion.dimension_id for criterion in self.criteria]
        deduction_ids = [deduction.deduction_id for deduction in self.deductions]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("复核维度不能重复")
        if len(set(deduction_ids)) != len(deduction_ids):
            raise ValueError("复核扣分项不能重复")
        return self


class ReviewAttemptView(BaseModel):
    """允许教师看到的 AI 结果；排除原始响应和计费元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    attempt_number: int = Field(gt=0)
    scoring_round: int = Field(gt=0)
    model: str = Field(min_length=1, max_length=300)
    subtotal: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    deduction_total: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    total_score: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    dimensions: tuple[DimensionResult, ...] = Field(min_length=1, max_length=100)
    deductions: tuple[DeductionResult, ...] = Field(max_length=100)
    overall_feedback: str = Field(min_length=1, max_length=20_000)

    @field_validator("overall_feedback")
    @classmethod
    def validate_feedback_language(cls, value: str) -> str:
        return str(require_english_narrative(value, "总体反馈"))


class ReviewDraftData(BaseModel):
    """通过严格评分契约后才允许进入仓储的规范草稿。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: UUID
    criteria: tuple[ReviewCriterionInput, ...]
    deductions: tuple[ReviewDeductionInput, ...]
    evidence: tuple[ReviewEvidenceInput, ...]
    overall_feedback: str
    change_reason: str | None
    subtotal: Decimal
    deduction_total: Decimal
    final_score: Decimal


class ReviewDraftView(ReviewDraftData):
    """教师草稿或不可变确认结果的安全投影。"""

    id: UUID
    revision_number: int = Field(gt=0)
    status: Literal["draft", "confirmed"]
    confirmed_at: datetime | None


class ReviewTarget(BaseModel):
    """仓储交给服务层的内部快照；对象路径绝不进入 API 响应。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_id: UUID
    job_id: UUID
    item_id: UUID
    item_status: str
    assignment_id: UUID
    assignment_title: str
    assignment_instructions: str
    rubric_version_id: UUID
    rubric_version: int = Field(gt=0)
    rubric: StructuredRubric
    submission_id: UUID
    original_filename: str
    submission_status: str
    extracted_object_key: str | None
    attempt: ReviewAttemptView
    draft: ReviewDraftView | None


class ReviewDetail(BaseModel):
    """教师工作台详情的最小安全响应。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    item_id: UUID
    item_status: str
    assignment_id: UUID
    assignment_title: str
    assignment_instructions: str
    rubric_version_id: UUID
    rubric_version: int
    rubric: StructuredRubric
    submission_id: UUID
    original_filename: str
    document: ParsedDocument
    attempt: ReviewAttemptView
    draft: ReviewDraftView | None


class ReviewConfirmationRef(BaseModel):
    """批量确认只引用已经过服务端校验的明确草稿版本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: UUID
    review_id: UUID
    revision_number: int = Field(gt=0)


class ReviewBatchConfirmationInput(BaseModel):
    """批量确认只能引用当前已保存的明确草稿版本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reviews: tuple[ReviewConfirmationRef, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_items_and_reviews(self) -> Self:
        item_ids = [review.item_id for review in self.reviews]
        review_ids = [review.review_id for review in self.reviews]
        if len(set(item_ids)) != len(item_ids) or len(set(review_ids)) != len(review_ids):
            raise ValueError("批量确认不能包含重复论文或复核")
        return self


class ReviewConfirmationResult(BaseModel):
    """单篇和批量确认共享的确定性结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reviews: tuple[ReviewDraftView, ...] = Field(min_length=1, max_length=100)
    completed_job_ids: tuple[UUID, ...] = Field(max_length=100)
