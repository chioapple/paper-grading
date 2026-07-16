"""阶段六作业与 Rubric 的公开数据契约。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.rubric import StructuredRubric

AssignmentState = Literal["draft", "ready", "archived"]
RubricState = Literal["draft", "confirmed", "superseded"]


class AssignmentCreate(BaseModel):
    """原子创建作业和首个 Rubric 草稿。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    instructions: str = Field(min_length=1, max_length=100_000)
    original_rubric: str = Field(min_length=1, max_length=100_000)
    total_score: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    score_step: Decimal = Field(gt=0, max_digits=10, decimal_places=4)

    @field_validator("title", "instructions", "original_rubric", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def validate_score_range(self) -> "AssignmentCreate":
        if self.score_step > self.total_score or self.total_score % self.score_step != 0:
            raise ValueError("总分必须能被评分步长整除")
        return self


class AssignmentUpdate(BaseModel):
    """替换草稿作业的题目与要求。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    instructions: str = Field(min_length=1, max_length=100_000)

    @field_validator("title", "instructions", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value


class AssignmentStatusUpdate(BaseModel):
    """显式归档或恢复作业；就绪状态只由确认 Rubric 产生。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["draft", "archived"]


class RubricDraftCreate(BaseModel):
    """为作业创建下一版原始 Rubric 草稿。"""

    model_config = ConfigDict(extra="forbid")

    original_rubric: str = Field(min_length=1, max_length=100_000)
    total_score: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    score_step: Decimal = Field(gt=0, max_digits=10, decimal_places=4)

    @field_validator("original_rubric", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def validate_score_range(self) -> "RubricDraftCreate":
        if self.score_step > self.total_score or self.total_score % self.score_step != 0:
            raise ValueError("总分必须能被评分步长整除")
        return self


class RubricStructureRequest(BaseModel):
    """教师只选择供应商；模型固定取管理员默认值。"""

    model_config = ConfigDict(extra="forbid")

    provider_config_id: UUID


class RubricStructuredUpdate(BaseModel):
    """教师用完整对象替换模型生成的结构化草稿。"""

    model_config = ConfigDict(extra="forbid")

    structured_rubric: StructuredRubric


class RubricView(BaseModel):
    """教师可见的 Rubric 版本与生成快照。"""

    id: UUID
    assignment_id: UUID
    version: int
    status: RubricState
    original_rubric: str
    structured_rubric: StructuredRubric | None
    total_score: Decimal
    score_step: Decimal
    provider_config_id: UUID | None
    model: str | None
    confirmed_at: datetime | None
    created_at: datetime


class RubricPointer(BaseModel):
    """列表直接使用的当前版本指针。"""

    id: UUID
    version: int
    status: RubricState


class AssignmentSummary(BaseModel):
    """作业列表所需的当前版本摘要。"""

    id: UUID
    title: str
    status: AssignmentState
    current_rubric_status: RubricState | None
    current_rubric_version: int | None
    current_draft_version: int | None
    current_confirmed_version: int | None
    current_draft: RubricPointer | None = None
    current_confirmed: RubricPointer | None = None
    created_at: datetime
    updated_at: datetime


class AssignmentDetail(AssignmentSummary):
    """作业详情及按版本倒序排列的 Rubric。"""

    instructions: str
    rubric_versions: list[RubricView]
