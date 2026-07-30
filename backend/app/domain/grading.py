"""阶段八与供应商无关的统一评分契约。"""

import hashlib
import json
import unicodedata
from decimal import Decimal
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
)

from app.domain.rubric import StructuredRubric
from app.parsing.models import ParsedDocument

GRADE_REQUEST_VERSION: Final[Literal["grade-request.v1"]] = "grade-request.v1"
GRADE_RESULT_SCHEMA_VERSION: Final[Literal["grade-result.v1"]] = "grade-result.v1"


def _require_decimal_string(value: object) -> object:
    """模型分数必须是 JSON 字符串，禁止二进制浮点进入评分契约。"""

    if not isinstance(value, str):
        raise ValueError("分数必须使用十进制字符串")
    return value


ModelDecimal = Annotated[
    Decimal,
    BeforeValidator(_require_decimal_string, json_schema_input_type=str),
    Field(max_digits=10, decimal_places=4),
]
RevisionSuggestion = Annotated[str, Field(min_length=1, max_length=4000)]


def require_english_narrative(value: object, field_name: str) -> object:
    """叙述字段只允许拉丁字母，明确拒绝中文等其他文字脚本。"""

    if not isinstance(value, str):
        return value
    has_latin_letter = False
    for character in value:
        if not character.isalpha():
            continue
        if "LATIN" not in unicodedata.name(character, ""):
            raise ValueError(f"{field_name}必须使用英文")
        has_latin_letter = True
    if not has_latin_letter:
        raise ValueError(f"{field_name}必须包含英文字母")
    return value


class GradeRequest(BaseModel):
    """一次评分所需的完整、可哈希输入快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["grade-request.v1"] = GRADE_REQUEST_VERSION
    assignment_id: UUID
    assignment_title: str = Field(min_length=1, max_length=300)
    assignment_instructions: str = Field(min_length=1, max_length=100_000)
    rubric_version_id: UUID
    rubric_version: int = Field(gt=0)
    rubric: StructuredRubric
    submission_id: UUID
    document: ParsedDocument
    feedback_language: Literal["en"] = "en"

    @field_validator("assignment_title", "assignment_instructions", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value


class EvidenceQuote(BaseModel):
    """由规范文本块定位的逐字证据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str = Field(pattern=r"^b[0-9]{6}$")
    quote: str = Field(min_length=1, max_length=20_000)

    @field_validator("quote")
    @classmethod
    def validate_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("证据原文不能为空")
        return value


class DimensionResult(BaseModel):
    """模型对一个 Rubric 维度的建议。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    score: ModelDecimal
    reason: str = Field(min_length=1, max_length=10_000)
    evidence: tuple[EvidenceQuote, ...] = Field(min_length=1, max_length=100)
    revision_suggestions: tuple[RevisionSuggestion, ...] = Field(
        min_length=1,
        max_length=50,
    )

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("评分理由不能为空")
        return require_english_narrative(value, "评分理由")

    @field_validator("revision_suggestions")
    @classmethod
    def normalize_suggestions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("修改建议不能为空")
        for value in values:
            require_english_narrative(value, "修改建议")
        return values


class DeductionResult(BaseModel):
    """模型只判断统一扣分是否适用，不得决定扣分值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    deduction_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    applied: StrictBool
    reason: str = Field(min_length=1, max_length=10_000)
    evidence: tuple[EvidenceQuote, ...] = Field(default_factory=tuple, max_length=100)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("扣分理由不能为空")
        return require_english_narrative(value, "扣分理由")


class GradeResult(BaseModel):
    """模型允许返回的严格结构；故意不包含总分。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["grade-result.v1"]
    dimensions: tuple[DimensionResult, ...] = Field(min_length=1, max_length=100)
    deductions: tuple[DeductionResult, ...] = Field(max_length=100)
    overall_feedback: str = Field(min_length=1, max_length=20_000)

    @field_validator("overall_feedback", mode="before")
    @classmethod
    def normalize_feedback(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("总体反馈不能为空")
        return require_english_narrative(value, "总体反馈")


class ValidatedGradeResult(GradeResult):
    """通过全部证据与 Rubric 校验后，由后端补充确定性总分。"""

    subtotal: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    deduction_total: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    total_score: Decimal = Field(ge=0, max_digits=10, decimal_places=4)


def _canonical_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        decimal_text = format(value, "f")
        if "." in decimal_text:
            decimal_text = decimal_text.rstrip("0").rstrip(".")
        return "0" if decimal_text in {"-0", ""} else decimal_text
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("规范 JSON 的对象键必须是字符串")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"不支持写入规范 JSON 的类型: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """生成版本与哈希共用的唯一 UTF-8 JSON 表示。"""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> bytes:
    """对规范 JSON 计算数据库使用的 32 字节 SHA-256。"""

    return hashlib.sha256(canonical_json_bytes(value)).digest()
