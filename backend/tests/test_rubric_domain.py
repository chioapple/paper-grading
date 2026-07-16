"""结构化 Rubric 领域契约测试。"""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.domain.rubric import StructuredRubric


def valid_rubric_payload() -> dict[str, Any]:
    """返回覆盖阶段六全部字段的最小合法 Rubric。"""

    return {
        "schema_version": 1,
        "total_score": "20",
        "score_step": "1",
        "dimensions": [
            {
                "id": "content",
                "name": "Content",
                "description": "Addresses the task with relevant ideas.",
                "max_score": "20",
                "bands": [
                    {
                        "label": "Needs revision",
                        "min_score": "0",
                        "max_score": "9",
                        "description": "The response is incomplete or mostly irrelevant.",
                    },
                    {
                        "label": "Meets expectations",
                        "min_score": "10",
                        "max_score": "20",
                        "description": "The response addresses the task with relevant support.",
                    },
                ],
                "evidence_requirements": ["Quote at least one relevant sentence."],
            }
        ],
        "deductions": [
            {
                "id": "missing_title",
                "name": "Missing title",
                "description": "Apply once when the essay has no title.",
                "points": "1",
            }
        ],
    }


def test_complete_structured_rubric_is_accepted() -> None:
    rubric = StructuredRubric.model_validate(valid_rubric_payload())

    assert rubric.total_score == 20
    assert rubric.dimensions[0].bands[-1].max_score == 20
    assert rubric.model_dump(mode="json")["score_step"] == "1"


def test_dimension_ids_must_be_unique() -> None:
    payload = valid_rubric_payload()
    duplicate = deepcopy(payload["dimensions"][0])
    duplicate["name"] = "Organization"
    payload["dimensions"].append(duplicate)
    payload["dimensions"][0]["max_score"] = "10"
    payload["dimensions"][1]["max_score"] = "10"

    with pytest.raises(ValidationError, match="维度 ID 不能重复"):
        StructuredRubric.model_validate(payload)


def test_dimension_names_must_be_unique_after_normalization() -> None:
    payload = valid_rubric_payload()
    duplicate = deepcopy(payload["dimensions"][0])
    duplicate["id"] = "organization"
    duplicate["name"] = "  content  "
    payload["dimensions"].append(duplicate)

    with pytest.raises(ValidationError, match="维度名称不能重复"):
        StructuredRubric.model_validate(payload)


def test_dimension_scores_must_sum_to_total_score() -> None:
    payload = valid_rubric_payload()
    payload["dimensions"][0]["max_score"] = "19"

    with pytest.raises(ValidationError, match="维度分值之和必须等于总分"):
        StructuredRubric.model_validate(payload)


def test_every_score_must_follow_the_declared_step() -> None:
    payload = valid_rubric_payload()
    payload["score_step"] = "3"

    with pytest.raises(ValidationError, match="所有分值必须符合评分步长"):
        StructuredRubric.model_validate(payload)


def test_score_bands_must_cover_dimension_without_gaps() -> None:
    payload = valid_rubric_payload()
    payload["dimensions"][0]["bands"][1]["min_score"] = "11"

    with pytest.raises(ValidationError, match="分档必须连续覆盖维度分值范围"):
        StructuredRubric.model_validate(payload)


def test_evidence_requirements_cannot_be_blank() -> None:
    payload = valid_rubric_payload()
    payload["dimensions"][0]["evidence_requirements"] = ["   "]

    with pytest.raises(ValidationError, match="证据要求不能为空"):
        StructuredRubric.model_validate(payload)


def test_descriptions_cannot_contain_only_whitespace() -> None:
    payload = valid_rubric_payload()
    payload["dimensions"][0]["description"] = "   "

    with pytest.raises(ValidationError, match="文本不能为空"):
        StructuredRubric.model_validate(payload)


def test_uniform_deduction_cannot_exceed_total_score() -> None:
    payload = valid_rubric_payload()
    payload["deductions"][0]["points"] = "21"

    with pytest.raises(ValidationError, match="统一扣分不能超过总分"):
        StructuredRubric.model_validate(payload)


def test_deduction_ids_and_names_must_be_unique() -> None:
    payload = valid_rubric_payload()
    duplicate = deepcopy(payload["deductions"][0])
    payload["deductions"].append(duplicate)

    with pytest.raises(ValidationError, match="扣分项 ID 不能重复"):
        StructuredRubric.model_validate(payload)


def test_scores_cannot_exceed_four_decimal_places() -> None:
    payload = valid_rubric_payload()
    payload["score_step"] = "0.00001"

    with pytest.raises(ValidationError):
        StructuredRubric.model_validate(payload)


def test_scores_must_fit_postgres_numeric_precision() -> None:
    payload = valid_rubric_payload()
    payload["total_score"] = "1000000"
    payload["dimensions"][0]["max_score"] = "1000000"
    payload["dimensions"][0]["bands"] = [
        {
            "label": "Full range",
            "min_score": "0",
            "max_score": "1000000",
            "description": "Covers the full score range.",
        }
    ]

    with pytest.raises(ValidationError):
        StructuredRubric.model_validate(payload)
