"""阶段六结构化 Rubric 的严格领域契约。"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RubricBand(BaseModel):
    """一个评分维度内连续且可解释的分数档。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=120)
    min_score: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    max_score: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    description: str = Field(min_length=1, max_length=4000)

    @field_validator("label", "description", mode="before")
    @classmethod
    def validate_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("文本不能为空")
        return value


class RubricDimension(BaseModel):
    """一项独立评分维度。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    max_score: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    bands: tuple[RubricBand, ...] = Field(min_length=1, max_length=50)
    evidence_requirements: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("name", "description", mode="before")
    @classmethod
    def validate_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("文本不能为空")
        return value

    @field_validator("evidence_requirements")
    @classmethod
    def validate_evidence_requirements(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(" ".join(value.split()) for value in values)
        if any(not value for value in cleaned):
            raise ValueError("证据要求不能为空")
        return cleaned


class RubricDeduction(BaseModel):
    """适用于全部维度之外的一项统一扣分。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    points: Decimal = Field(gt=0, max_digits=10, decimal_places=4)

    @field_validator("name", "description", mode="before")
    @classmethod
    def validate_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("文本不能为空")
        return value


class StructuredRubric(BaseModel):
    """可冻结、可版本化的完整 Rubric。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    total_score: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    score_step: Decimal = Field(gt=0, max_digits=10, decimal_places=4)
    dimensions: tuple[RubricDimension, ...] = Field(min_length=1, max_length=100)
    deductions: tuple[RubricDeduction, ...] = Field(default_factory=tuple, max_length=100)

    @model_validator(mode="after")
    def validate_unique_dimension_ids(self) -> "StructuredRubric":
        dimension_ids = [dimension.id for dimension in self.dimensions]
        if len(set(dimension_ids)) != len(dimension_ids):
            raise ValueError("维度 ID 不能重复")
        dimension_names = [
            " ".join(dimension.name.split()).casefold() for dimension in self.dimensions
        ]
        if len(set(dimension_names)) != len(dimension_names):
            raise ValueError("维度名称不能重复")
        deduction_ids = [deduction.id for deduction in self.deductions]
        if len(set(deduction_ids)) != len(deduction_ids):
            raise ValueError("扣分项 ID 不能重复")
        deduction_names = [
            " ".join(deduction.name.split()).casefold() for deduction in self.deductions
        ]
        if len(set(deduction_names)) != len(deduction_names):
            raise ValueError("扣分项名称不能重复")
        if sum(dimension.max_score for dimension in self.dimensions) != self.total_score:
            raise ValueError("维度分值之和必须等于总分")
        scores = [self.total_score]
        scores.extend(dimension.max_score for dimension in self.dimensions)
        scores.extend(
            score
            for dimension in self.dimensions
            for band in dimension.bands
            for score in (band.min_score, band.max_score)
        )
        scores.extend(deduction.points for deduction in self.deductions)
        if self.score_step > self.total_score or any(
            score % self.score_step != 0 for score in scores
        ):
            raise ValueError("所有分值必须符合评分步长")
        if any(deduction.points > self.total_score for deduction in self.deductions):
            raise ValueError("统一扣分不能超过总分")
        for dimension in self.dimensions:
            previous_max: Decimal | None = None
            for band in dimension.bands:
                expected_min = (
                    Decimal(0) if previous_max is None else previous_max + self.score_step
                )
                if (
                    band.min_score != expected_min
                    or band.min_score > band.max_score
                    or band.max_score > dimension.max_score
                ):
                    raise ValueError("分档必须连续覆盖维度分值范围")
                previous_max = band.max_score
            if previous_max != dimension.max_score:
                raise ValueError("分档必须连续覆盖维度分值范围")
        return self
