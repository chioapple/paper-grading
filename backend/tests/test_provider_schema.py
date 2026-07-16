"""供应商严格结构化输出 Schema 投影测试。"""

from app.domain.grading import GradeResult, canonical_json_bytes
from app.providers.schema import compile_provider_schema


def test_openai_schema_projection_is_strict_and_removes_pydantic_only_keywords() -> None:
    compiled = compile_provider_schema(
        canonical_json_bytes(GradeResult.model_json_schema(mode="validation")),
        dialect="openai",
    )

    properties = compiled.schema_body["properties"]
    assert isinstance(properties, dict)
    assert compiled.schema_body["required"] == list(properties)
    assert compiled.schema_body["additionalProperties"] is False
    assert b"decimal_places" not in compiled.canonical_json
    assert b"max_digits" not in compiled.canonical_json
    assert b'"const"' not in compiled.canonical_json
    assert b'"enum":["grade-result.v1"]' in compiled.canonical_json
