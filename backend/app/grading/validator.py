"""模型评分结果进入系统前的唯一严格校验入口。"""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.domain.grading import (
    GradeRequest,
    GradeResult,
    ValidatedGradeResult,
    canonical_sha256,
)
from app.grading.totals import calculate_grade_totals


class GradeValidationError(ValueError):
    """稳定暴露给后续评分流水线的契约错误。"""

    def __init__(self, code: str, message: str, *, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class GradeValidationIssue(BaseModel):
    """可写入审计记录、可安全发给同模型纠正的稳定问题。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,127}$")
    path: str = Field(min_length=1, max_length=500)


class GradeValidationOutcome(BaseModel):
    """一次完整模型正文经过校验后的流水线决定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted", "correction_required", "needs_review"]
    code: str | None = None
    attempt_count: Literal[1, 2]
    result: ValidatedGradeResult | None = None
    issues: tuple[GradeValidationIssue, ...] = Field(default_factory=tuple, max_length=100)

    @model_validator(mode="after")
    def validate_shape(self) -> "GradeValidationOutcome":
        if self.status == "accepted":
            if self.result is None or self.code is not None or self.issues:
                raise ValueError("已接受结果的状态字段不一致")
        elif self.result is not None or self.code is None or not self.issues:
            raise ValueError("未通过校验的状态字段不一致")
        if (
            self.status == "correction_required"
            and self.attempt_count != 1
            or self.status == "needs_review"
            and self.attempt_count != 2
        ):
            raise ValueError("校验状态与调用次数不一致")
        return self


def _first_validation_path(error: ValidationError) -> str:
    details = error.errors(include_url=False, include_context=False)
    if not details:
        return "$"
    if details[0]["type"] == "extra_forbidden":
        return "$"
    path = "$"
    for part in details[0]["loc"]:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path


class GradingCall(Protocol):
    """校验器只依赖提示词快照的不可变调用边界。"""

    @property
    def base_request_hash(self) -> bytes: ...

    @property
    def messages(self) -> Sequence[object]: ...


def _require_exact_ids(
    actual_ids: Sequence[str],
    expected_ids: Sequence[str],
    *,
    label: str,
) -> None:
    if len(set(actual_ids)) != len(actual_ids):
        raise GradeValidationError(
            f"grade_{label}_duplicate",
            f"模型返回了重复的{label} ID",
        )
    if list(actual_ids) != list(expected_ids):
        raise GradeValidationError(
            f"grade_{label}_mismatch",
            f"模型返回的{label}与评分标准不一致",
        )


def _validate_evidence(result: GradeResult, request: GradeRequest) -> None:
    block_text = {block.block_id: block.text for block in request.document.blocks}
    evidence_groups = [dimension.evidence for dimension in result.dimensions]
    evidence_groups.extend(deduction.evidence for deduction in result.deductions)
    for evidence_group in evidence_groups:
        seen: set[tuple[str, str]] = set()
        for evidence in evidence_group:
            key = (evidence.block_id, evidence.quote)
            if key in seen:
                raise GradeValidationError(
                    "grade_evidence_duplicate",
                    "同一评分项不能重复引用完全相同的证据",
                )
            seen.add(key)
            source = block_text.get(evidence.block_id)
            if source is None:
                raise GradeValidationError(
                    "grade_evidence_block_unknown",
                    "模型引用了不存在的文本块",
                )
            if evidence.quote not in source:
                raise GradeValidationError(
                    "grade_evidence_quote_mismatch",
                    "模型证据没有逐字出现在指定文本块中",
                )


def validate_grade_response(
    raw_result: object,
    request: GradeRequest,
) -> ValidatedGradeResult:
    """拒绝任何缺失、越界或证据不实的输出，再由后端计算总分。"""

    try:
        result = GradeResult.model_validate(raw_result)
    except ValidationError as error:
        raise GradeValidationError(
            "grade_output_schema_invalid",
            "模型没有返回有效的统一评分结构",
            path=_first_validation_path(error),
        ) from error

    expected_dimension_ids = [dimension.id for dimension in request.rubric.dimensions]
    actual_dimension_ids = [dimension.dimension_id for dimension in result.dimensions]
    _require_exact_ids(
        actual_dimension_ids,
        expected_dimension_ids,
        label="dimension",
    )
    for dimension_result, dimension in zip(
        result.dimensions,
        request.rubric.dimensions,
        strict=True,
    ):
        if (
            dimension_result.score < 0
            or dimension_result.score > dimension.max_score
            or dimension_result.score % request.rubric.score_step != 0
        ):
            raise GradeValidationError(
                "grade_dimension_score_invalid",
                "模型分数越界或不符合评分步长",
            )

    expected_deduction_ids = [deduction.id for deduction in request.rubric.deductions]
    actual_deduction_ids = [deduction.deduction_id for deduction in result.deductions]
    _require_exact_ids(
        actual_deduction_ids,
        expected_deduction_ids,
        label="deduction",
    )
    _validate_evidence(result, request)

    totals = calculate_grade_totals(result, request.rubric)
    return ValidatedGradeResult.model_validate(
        {
            **result.model_dump(mode="json"),
            "subtotal": totals.subtotal,
            "deduction_total": totals.deduction_total,
            "total_score": totals.total_score,
        }
    )


def assess_grade_response(
    raw_result: object,
    request: GradeRequest,
    *,
    prompt: GradingCall,
) -> GradeValidationOutcome:
    """首次失败要求同模型纠正一次；第二次失败立即交教师复核。"""

    if prompt.base_request_hash != canonical_sha256(request):
        raise GradeValidationError(
            "grade_request_snapshot_mismatch",
            "评分请求与已保存提示词快照不一致",
        )
    if len(prompt.messages) == 2:
        attempt_count: Literal[1, 2] = 1
    elif len(prompt.messages) == 3:
        attempt_count = 2
    else:
        raise ValueError("评分调用只能是初次请求或唯一一次纠正")
    try:
        result = validate_grade_response(raw_result, request)
    except GradeValidationError as error:
        issue = GradeValidationIssue(code=error.code, path=error.path)
        if attempt_count == 1:
            return GradeValidationOutcome(
                status="correction_required",
                code="grade_output_correction_required",
                attempt_count=attempt_count,
                issues=(issue,),
            )
        return GradeValidationOutcome(
            status="needs_review",
            code="grade_output_invalid_after_correction",
            attempt_count=attempt_count,
            issues=(issue,),
        )
    return GradeValidationOutcome(
        status="accepted",
        attempt_count=attempt_count,
        result=result,
    )
