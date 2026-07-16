"""以交互式密钥执行阶段九 DeepSeek 真实评分冒烟，不读取 Supabase。"""

import asyncio
import json
from decimal import Decimal
from getpass import getpass
from uuid import UUID

from pydantic import SecretStr

from app.domain.enums import ProviderType
from app.domain.grading import GradeRequest, GradeResult, canonical_json_bytes
from app.domain.rubric import RubricBand, RubricDimension, StructuredRubric
from app.grading.prompt import build_correction_prompt, build_grading_prompt
from app.grading.validator import assess_grade_response
from app.parsing.models import (
    PDF_MEDIA_TYPE,
    DocumentBlock,
    ParsedDocument,
    PdfTextBlockLocator,
)
from app.providers.base import (
    ProviderAdapterError,
    ProviderGradeRequest,
    ProviderModelCapabilities,
)
from app.providers.connection import ProviderBaseUrlPolicy
from app.providers.deepseek import DeepSeekAdapter
from app.providers.http import HttpCoreProviderAdapterClient


def build_smoke_grade_request() -> GradeRequest:
    """使用无真实学生信息的最小英语样本。"""

    rubric = StructuredRubric(
        schema_version=1,
        total_score=Decimal("5"),
        score_step=Decimal("1"),
        dimensions=[
            RubricDimension(
                id="argument",
                name="Argument",
                description="Quality of the central claim and support.",
                max_score=Decimal("5"),
                bands=[
                    RubricBand(
                        label="Not demonstrated",
                        min_score=Decimal("0"),
                        max_score=Decimal("0"),
                        description="No assessable argument.",
                    ),
                    RubricBand(
                        label="Demonstrated",
                        min_score=Decimal("1"),
                        max_score=Decimal("5"),
                        description="An assessable argument with varying support.",
                    ),
                ],
                evidence_requirements=["Quote the claim or supporting reason."],
            )
        ],
        deductions=[],
    )
    document = ParsedDocument(
        media_type=PDF_MEDIA_TYPE,
        page_count=1,
        character_count=100,
        blocks=[
            DocumentBlock(
                block_id="b000001",
                text=(
                    "Public transport should be free because it reduces traffic and helps "
                    "students reach school reliably."
                ),
                locator=PdfTextBlockLocator(
                    page=1,
                    block=1,
                    bbox=(10.0, 20.0, 500.0, 40.0),
                ),
            )
        ],
    )
    return GradeRequest(
        assignment_id=UUID("11111111-1111-4111-8111-111111111111"),
        assignment_title="Argumentative essay",
        assignment_instructions="Explain whether public transport should be free.",
        rubric_version_id=UUID("22222222-2222-4222-8222-222222222222"),
        rubric_version=1,
        rubric=rubric,
        submission_id=UUID("33333333-3333-4333-8333-333333333333"),
        document=document,
    )


def require_positive_integer(label: str) -> int:
    raw_value = input(label).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError("必须输入正整数") from error
    if value <= 0:
        raise ValueError("必须输入正整数")
    return value


async def run_smoke() -> dict[str, object]:
    model = input("DeepSeek 已配置模型 ID: ").strip()
    if not model:
        raise ValueError("模型 ID 不能为空")
    context_window_tokens = require_positive_integer("已确认的上下文 Token 上限: ")
    model_max_output_tokens = require_positive_integer("已确认的模型输出 Token 上限: ")
    call_max_output_tokens = require_positive_integer("本次调用输出 Token 上限: ")
    api_key = getpass("DeepSeek API Key（不会回显或保存）: ")
    if not api_key:
        raise ValueError("API Key 不能为空")

    grade_request = build_smoke_grade_request()
    prompt = build_grading_prompt(grade_request)
    provider_request = ProviderGradeRequest(
        provider_config_id=UUID("99999999-9999-4999-8999-999999999999"),
        config_version=1,
        provider_type=ProviderType.DEEPSEEK,
        base_url="https://api.deepseek.com",
        api_key=SecretStr(api_key),
        model=model,
        timeout_seconds=Decimal("120"),
        max_output_tokens=call_max_output_tokens,
        capabilities=ProviderModelCapabilities(
            capability_version="manual-stage9-smoke.v1",
            model=model,
            context_window_tokens=context_window_tokens,
            max_output_tokens=model_max_output_tokens,
            structured_output="json_object",
            schema_dialect="canonical",
            sampling_policy="temperature_zero",
            thinking_policy="disabled",
            output_token_parameter="max_tokens",
            supports_model_listing=True,
        ),
        result_schema_json=canonical_json_bytes(GradeResult.model_json_schema(mode="validation")),
        prompt=prompt,
    )
    adapter = DeepSeekAdapter(
        url_policy=ProviderBaseUrlPolicy(),
        http_client=HttpCoreProviderAdapterClient(),
    )
    first_result = await adapter.grade(provider_request)
    try:
        first_json = json.loads(first_result.output_text)
    except json.JSONDecodeError:
        first_json = None
    outcome = assess_grade_response(first_json, grade_request, prompt=prompt)
    result = first_result
    if outcome.status == "correction_required":
        correction_prompt = build_correction_prompt(
            prompt,
            outcome=outcome,
            invalid_output=first_result.output_text,
        )
        correction_request = provider_request.model_copy(update={"prompt": correction_prompt})
        if correction_request.snapshot_hash() != provider_request.snapshot_hash():
            raise RuntimeError("纠正调用改变了不可变供应商快照")
        result = await adapter.grade(correction_request)
        try:
            corrected_json = json.loads(result.output_text)
        except json.JSONDecodeError:
            corrected_json = None
        outcome = assess_grade_response(
            corrected_json,
            grade_request,
            prompt=correction_prompt,
        )
    if outcome.status != "accepted" or outcome.result is None:
        raise RuntimeError("真实模型两次输出均未通过评分契约")
    return {
        "status": "accepted",
        "provider": result.provider_type.value,
        "model": result.reported_model,
        "request_id": result.request_id,
        "attempt_count": outcome.attempt_count,
        "usage": result.usage.model_dump(),
        "total_score": str(outcome.result.total_score),
        "raw_response_sha256": result.raw_response_sha256.hex(),
    }


def main() -> int:
    try:
        result = asyncio.run(run_smoke())
    except ProviderAdapterError as error:
        print(json.dumps({"status": "failed", "code": error.code}, ensure_ascii=False))
        return 1
    except (RuntimeError, ValueError) as error:
        print(json.dumps({"status": "failed", "message": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
