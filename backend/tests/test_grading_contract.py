"""阶段八统一评分契约的行为测试。"""

from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.grading import GradeRequest
from app.domain.rubric import (
    RubricBand,
    RubricDeduction,
    RubricDimension,
    StructuredRubric,
)
from app.grading.prompt import build_correction_prompt, build_grading_prompt
from app.grading.validator import (
    GradeValidationError,
    GradeValidationIssue,
    GradeValidationOutcome,
    assess_grade_response,
    validate_grade_response,
)
from app.parsing.models import (
    PDF_MEDIA_TYPE,
    DocumentBlock,
    ParsedDocument,
    PdfTextBlockLocator,
)


def build_request() -> GradeRequest:
    rubric = StructuredRubric(
        schema_version=1,
        total_score=Decimal("10"),
        score_step=Decimal("1"),
        dimensions=[
            RubricDimension(
                id="argument",
                name="Argument",
                description="Quality of the central argument.",
                max_score=Decimal("5"),
                bands=[
                    RubricBand(
                        label="Not demonstrated",
                        min_score=Decimal("0"),
                        max_score=Decimal("0"),
                        description="No assessable argument.",
                    ),
                    RubricBand(
                        label="Developing",
                        min_score=Decimal("1"),
                        max_score=Decimal("3"),
                        description="A partly supported argument.",
                    ),
                    RubricBand(
                        label="Strong",
                        min_score=Decimal("4"),
                        max_score=Decimal("5"),
                        description="A clear and well-supported argument.",
                    ),
                ],
                evidence_requirements=["Quote the thesis or a supporting claim."],
            ),
            RubricDimension(
                id="language",
                name="Language",
                description="Clarity and control of written English.",
                max_score=Decimal("5"),
                bands=[
                    RubricBand(
                        label="Not demonstrated",
                        min_score=Decimal("0"),
                        max_score=Decimal("0"),
                        description="No assessable language.",
                    ),
                    RubricBand(
                        label="Developing",
                        min_score=Decimal("1"),
                        max_score=Decimal("3"),
                        description="Meaning is uneven but recoverable.",
                    ),
                    RubricBand(
                        label="Strong",
                        min_score=Decimal("4"),
                        max_score=Decimal("5"),
                        description="Meaning is consistently clear.",
                    ),
                ],
                evidence_requirements=["Quote representative wording."],
            ),
        ],
        deductions=[
            RubricDeduction(
                id="missing_title",
                name="Missing title",
                description="Deduct one point when the essay has no title.",
                points=Decimal("1"),
            )
        ],
    )
    document = ParsedDocument(
        media_type=PDF_MEDIA_TYPE,
        page_count=1,
        character_count=112,
        blocks=[
            DocumentBlock(
                block_id="b000001",
                text="Public transport should be free because it reduces traffic.",
                locator=PdfTextBlockLocator(
                    page=1,
                    block=1,
                    bbox=(10.0, 20.0, 300.0, 40.0),
                ),
            ),
            DocumentBlock(
                block_id="b000002",
                text="This policy makes cities cleaner and easier to reach.",
                locator=PdfTextBlockLocator(
                    page=1,
                    block=2,
                    bbox=(10.0, 50.0, 300.0, 70.0),
                ),
            ),
        ],
    )
    return GradeRequest(
        assignment_id=UUID("11111111-1111-4111-8111-111111111111"),
        assignment_title="Argumentative essay",
        assignment_instructions="Discuss whether public transport should be free.",
        rubric_version_id=UUID("22222222-2222-4222-8222-222222222222"),
        rubric_version=1,
        rubric=rubric,
        submission_id=UUID("33333333-3333-4333-8333-333333333333"),
        document=document,
    )


def valid_model_output() -> dict[str, object]:
    return {
        "schema_version": "grade-result.v1",
        "dimensions": [
            {
                "dimension_id": "argument",
                "score": "4",
                "reason": "The claim is clear and supported by a relevant benefit.",
                "evidence": [
                    {
                        "block_id": "b000001",
                        "quote": "it reduces traffic",
                    }
                ],
                "revision_suggestions": ["Explain how free access changes behaviour."],
            },
            {
                "dimension_id": "language",
                "score": "4",
                "reason": "The sentences are clear and controlled.",
                "evidence": [
                    {
                        "block_id": "b000002",
                        "quote": "cities cleaner and easier to reach",
                    }
                ],
                "revision_suggestions": ["Vary the sentence openings."],
            },
        ],
        "deductions": [
            {
                "deduction_id": "missing_title",
                "applied": True,
                "reason": "The submitted text has no title.",
                "evidence": [],
            }
        ],
        "overall_feedback": (
            "Your position is clear and readable. Add a fuller explanation of the causal "
            "link and vary the sentence structure."
        ),
    }


def test_valid_response_uses_only_backend_calculated_total() -> None:
    result = validate_grade_response(valid_model_output(), build_request())

    assert result.subtotal == Decimal("8")
    assert result.deduction_total == Decimal("1")
    assert result.total_score == Decimal("7")


def test_model_cannot_supply_a_total_score() -> None:
    output = valid_model_output()
    output["total_score"] = "10"

    with pytest.raises(GradeValidationError) as error:
        validate_grade_response(output, build_request())

    assert error.value.code == "grade_output_schema_invalid"


@pytest.mark.parametrize("field_name", ["schema_version", "deductions"])
def test_model_must_explicitly_return_every_top_level_contract_field(
    field_name: str,
) -> None:
    output = valid_model_output()
    del output[field_name]

    with pytest.raises(GradeValidationError) as error:
        validate_grade_response(output, build_request())

    assert error.value.code == "grade_output_schema_invalid"


@pytest.mark.parametrize(
    "dimension_ids",
    [
        ["argument"],
        ["argument", "argument"],
        ["argument", "unknown"],
        ["language", "argument"],
    ],
)
def test_dimension_ids_must_exactly_match_the_rubric(
    dimension_ids: list[str],
) -> None:
    output = valid_model_output()
    dimensions = output["dimensions"]
    assert isinstance(dimensions, list)
    output["dimensions"] = [
        {**dimensions[index], "dimension_id": dimension_id}
        for index, dimension_id in enumerate(dimension_ids)
    ]

    with pytest.raises(GradeValidationError) as error:
        validate_grade_response(output, build_request())

    assert error.value.code in {"grade_dimension_duplicate", "grade_dimension_mismatch"}


@pytest.mark.parametrize(
    ("score", "expected_code"),
    [
        ("6", "grade_dimension_score_invalid"),
        ("3.5", "grade_dimension_score_invalid"),
        (4, "grade_output_schema_invalid"),
        (4.0, "grade_output_schema_invalid"),
    ],
)
def test_dimension_scores_reject_range_step_and_json_number_errors(
    score: object,
    expected_code: str,
) -> None:
    output = valid_model_output()
    dimensions = output["dimensions"]
    assert isinstance(dimensions, list)
    first_dimension = dimensions[0]
    assert isinstance(first_dimension, dict)
    first_dimension["score"] = score

    with pytest.raises(GradeValidationError) as error:
        validate_grade_response(output, build_request())

    assert error.value.code == expected_code


@pytest.mark.parametrize(
    ("block_id", "quote", "expected_code"),
    [
        ("b999999", "it reduces traffic", "grade_evidence_block_unknown"),
        ("b000002", "it reduces traffic", "grade_evidence_quote_mismatch"),
        ("b000001", "It reduces traffic", "grade_evidence_quote_mismatch"),
        ("b000001", "it  reduces traffic", "grade_evidence_quote_mismatch"),
        ("b000001", "", "grade_output_schema_invalid"),
        ("b000001", " ", "grade_output_schema_invalid"),
        ("b000001", "\n\t", "grade_output_schema_invalid"),
    ],
)
def test_evidence_must_match_the_named_block_verbatim(
    block_id: str,
    quote: str,
    expected_code: str,
) -> None:
    output = valid_model_output()
    dimensions = output["dimensions"]
    assert isinstance(dimensions, list)
    first_dimension = dimensions[0]
    assert isinstance(first_dimension, dict)
    evidence = first_dimension["evidence"]
    assert isinstance(evidence, list)
    first_evidence = evidence[0]
    assert isinstance(first_evidence, dict)
    first_evidence.update({"block_id": block_id, "quote": quote})

    with pytest.raises(GradeValidationError) as error:
        validate_grade_response(output, build_request())

    assert error.value.code == expected_code


def test_model_cannot_choose_the_deduction_value() -> None:
    output = valid_model_output()
    deductions = output["deductions"]
    assert isinstance(deductions, list)
    first_deduction = deductions[0]
    assert isinstance(first_deduction, dict)
    first_deduction["points"] = "10"

    with pytest.raises(GradeValidationError) as error:
        validate_grade_response(output, build_request())

    assert error.value.code == "grade_output_schema_invalid"


def test_backend_total_stops_at_zero_after_fixed_deductions() -> None:
    output = valid_model_output()
    dimensions = output["dimensions"]
    assert isinstance(dimensions, list)
    for dimension in dimensions:
        assert isinstance(dimension, dict)
        dimension["score"] = "0"

    result = validate_grade_response(output, build_request())

    assert result.subtotal == Decimal("0")
    assert result.deduction_total == Decimal("1")
    assert result.total_score == Decimal("0")


def test_document_block_ids_must_be_unique_and_sequential() -> None:
    payload = build_request().document.model_dump(mode="json")
    payload["blocks"][1]["block_id"] = "b000001"

    with pytest.raises(ValidationError, match="文本块 ID 必须唯一且连续"):
        ParsedDocument.model_validate(payload)


def test_document_character_count_must_match_the_exact_blocks() -> None:
    payload = build_request().document.model_dump(mode="json")
    payload["character_count"] = sum(len(block["text"]) for block in payload["blocks"]) + 1

    with pytest.raises(ValidationError, match="字符数必须等于文本块原文长度之和"):
        ParsedDocument.model_validate(payload)


def test_grade_request_nested_collections_are_immutable() -> None:
    request = build_request()

    assert isinstance(request.document.blocks, tuple)
    assert isinstance(request.rubric.dimensions, tuple)
    assert isinstance(request.rubric.dimensions[0].bands, tuple)
    assert isinstance(request.rubric.dimensions[0].evidence_requirements, tuple)
    assert isinstance(request.rubric.deductions, tuple)


def test_only_one_schema_correction_is_allowed_before_needs_review() -> None:
    invalid_output = {"schema_version": "grade-result.v1"}
    request = build_request()
    initial_prompt = build_grading_prompt(request)

    first = assess_grade_response(
        invalid_output,
        request,
        prompt=initial_prompt,
    )
    correction_prompt = build_correction_prompt(
        initial_prompt,
        outcome=first,
        invalid_output='{"schema_version":"grade-result.v1"}',
    )
    second = assess_grade_response(
        invalid_output,
        request,
        prompt=correction_prompt,
    )

    assert first.status == "correction_required"
    assert first.result is None
    assert first.issues[0].code == "grade_output_schema_invalid"
    assert first.issues[0].path == "$.dimensions"
    assert second.status == "needs_review"
    assert second.result is None
    assert second.code == "grade_output_invalid_after_correction"
    with pytest.raises(ValueError, match="只允许纠正一次"):
        build_correction_prompt(
            correction_prompt,
            outcome=second,
            invalid_output='{"schema_version":"grade-result.v1"}',
        )


def test_valid_same_contract_correction_is_accepted_on_the_second_call() -> None:
    request = build_request()
    initial_prompt = build_grading_prompt(request)
    invalid = assess_grade_response(
        {"schema_version": "grade-result.v1"},
        request,
        prompt=initial_prompt,
    )
    correction_prompt = build_correction_prompt(
        initial_prompt,
        outcome=invalid,
        invalid_output='{"schema_version":"grade-result.v1"}',
    )
    outcome = assess_grade_response(
        valid_model_output(),
        request,
        prompt=correction_prompt,
    )

    assert outcome.status == "accepted"
    assert outcome.attempt_count == 2
    assert outcome.result is not None
    assert outcome.result.total_score == Decimal("7")


@pytest.mark.parametrize(
    ("status", "attempt_count"),
    [("correction_required", 2), ("needs_review", 1)],
)
def test_validation_failure_status_is_bound_to_the_call_count(
    status: str,
    attempt_count: int,
) -> None:
    with pytest.raises(ValidationError, match="校验状态与调用次数不一致"):
        GradeValidationOutcome(
            status=status,
            code="grade_output_invalid",
            attempt_count=attempt_count,
            issues=[GradeValidationIssue(code="grade_output_schema_invalid", path="$")],
        )
