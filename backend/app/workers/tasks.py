"""阶段十单篇评分执行器；Celery 包装只负责传入任务 ID。"""

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.domain.grading import (
    GradeRequest,
    ValidatedGradeResult,
    canonical_json_bytes,
)
from app.domain.rubric import StructuredRubric
from app.grading.prompt import (
    build_correction_prompt,
    build_grading_prompt,
    parse_prompt_version,
)
from app.grading.validator import (
    GradeValidationIssue,
    GradeValidationOutcome,
    assess_grade_response,
)
from app.parsing.models import ParsedDocument
from app.providers.base import ProviderAdapterError, ProviderGradeRequest, ProviderGradeResult
from app.providers.connection import ProviderUrlError
from app.providers.registry import ProviderAdapterRegistry
from app.security.encryption import ApiKeyCipher, EncryptedApiKey
from app.workers.models import GradingProviderSnapshot

AttemptKind = Literal["initial", "correction", "automatic_retry", "manual_retry"]
RunResult = Literal["completed", "duplicate", "retry_scheduled", "needs_review", "failed"]


class GradingItemPreparation(BaseModel):
    """调用供应商前从 PostgreSQL 读取的完整可信输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_id: UUID
    job_id: UUID
    item_id: UUID
    dispatch_version: int = Field(gt=0)
    submission_id: UUID
    extracted_object_key: str = Field(min_length=1)
    assignment_id: UUID
    assignment_title: str = Field(min_length=1)
    assignment_instructions: str = Field(min_length=1)
    rubric_version_id: UUID
    rubric_version: int = Field(gt=0)
    rubric: StructuredRubric
    provider_config_id: UUID
    provider_config_version: int = Field(gt=0)
    encrypted_api_key: bytes = Field(min_length=17, repr=False)
    api_key_nonce: bytes = Field(min_length=12, max_length=12, repr=False)
    model: str = Field(min_length=1)
    provider_snapshot: GradingProviderSnapshot
    prompt_version: str
    prompt_hash: bytes = Field(min_length=32, max_length=32)
    result_schema_version: str
    result_schema: dict[str, object]
    result_schema_hash: bytes = Field(min_length=32, max_length=32)
    rubric_hash: bytes = Field(min_length=32, max_length=32)
    attempt_kind: AttemptKind
    parent_attempt_id: UUID | None
    previous_response_object_key: str | None
    previous_error_details: dict[str, object] | None


class GradingAttemptClaim(BaseModel):
    """数据库原子 claim 后唯一允许执行外部调用的凭证。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_id: UUID
    attempt_number: int = Field(gt=0)
    scoring_round: int = Field(gt=0)
    call_sequence: int = Field(gt=0)
    lease_token: UUID
    request_hash: bytes = Field(min_length=32, max_length=32)


class GradingAttemptCompletion(BaseModel):
    """一次成功评分写回 PostgreSQL 的完整审计结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validated_result: ValidatedGradeResult
    provider_result: ProviderGradeResult
    response_object_key: str
    response_object_sha256: bytes = Field(min_length=32, max_length=32)


class GradingAttemptFailure(BaseModel):
    """失败调用的持久化决定；模糊结果永远不自动重试。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["retry", "needs_review", "failed"]
    retry_delay_seconds: int = Field(default=0, ge=0, le=3600)
    error_code: str = Field(min_length=1)
    error_details: dict[str, object] = Field(default_factory=dict)
    provider_call_state: Literal["not_sent", "response_received", "ambiguous"]
    provider_result: ProviderGradeResult | None = None
    provider_request_id: str | None = None
    response_object_key: str | None = None
    response_object_sha256: bytes | None = Field(default=None, min_length=32, max_length=32)


class GradingAttemptRepository(Protocol):
    async def prepare_item(
        self,
        item_id: UUID,
        dispatch_version: int,
    ) -> GradingItemPreparation | None: ...

    async def claim_attempt(
        self,
        prepared: GradingItemPreparation,
        request_hash: bytes,
    ) -> GradingAttemptClaim | None: ...

    async def finish_success(
        self,
        claim: GradingAttemptClaim,
        completion: GradingAttemptCompletion,
    ) -> None: ...

    async def finish_failure(
        self,
        claim: GradingAttemptClaim,
        failure: GradingAttemptFailure,
    ) -> None: ...


class GradingObjectStorage(Protocol):
    async def get_json(self, key: str) -> bytes: ...

    async def put_json_once(self, key: str, content: bytes) -> None: ...


def build_provider_response_object_key(
    preparation: GradingItemPreparation,
    attempt_id: UUID,
) -> str:
    """只由数据库 UUID 构造不可变原始响应审计路径。"""

    return (
        f"teachers/{preparation.owner_id}/grading-jobs/{preparation.job_id}/"
        f"items/{preparation.item_id}/attempts/{attempt_id}/provider-response.v1.json"
    )


class GradingAttemptRunner:
    """一个 Celery 消息只尝试 claim 一篇论文；重复消息不会调用供应商。"""

    def __init__(
        self,
        *,
        repository: GradingAttemptRepository,
        storage: GradingObjectStorage,
        adapters: ProviderAdapterRegistry,
        cipher: ApiKeyCipher,
        now: Callable[[], datetime],
        max_provider_retries: int = 2,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._adapters = adapters
        self._cipher = cipher
        self._now = now
        self._max_provider_retries = max_provider_retries

    async def run(self, item_id: UUID, dispatch_version: int) -> RunResult:
        prepared = await self._repository.prepare_item(item_id, dispatch_version)
        if prepared is None:
            return "duplicate"
        document = ParsedDocument.model_validate_json(
            await self._storage.get_json(prepared.extracted_object_key)
        )
        grade_request = GradeRequest(
            assignment_id=prepared.assignment_id,
            assignment_title=prepared.assignment_title,
            assignment_instructions=prepared.assignment_instructions,
            rubric_version_id=prepared.rubric_version_id,
            rubric_version=prepared.rubric_version,
            rubric=prepared.rubric,
            submission_id=prepared.submission_id,
            document=document,
        )
        initial_prompt = build_grading_prompt(
            grade_request,
            prompt_version=parse_prompt_version(prepared.prompt_version),
        )
        prompt = initial_prompt
        if prepared.previous_response_object_key is not None:
            if prepared.previous_error_details is None:
                raise RuntimeError("纠正调用缺少上次校验错误")
            previous_envelope = json.loads(
                await self._storage.get_json(prepared.previous_response_object_key)
            )
            previous_output = (
                previous_envelope.get("output_text")
                if isinstance(previous_envelope, dict)
                else None
            )
            raw_issues = prepared.previous_error_details.get("issues")
            if not isinstance(previous_output, str) or not isinstance(raw_issues, list):
                raise RuntimeError("纠正调用的上次响应审计对象无效")
            correction_outcome = GradeValidationOutcome(
                status="correction_required",
                code="grade_output_correction_required",
                attempt_count=1,
                issues=tuple(GradeValidationIssue.model_validate(issue) for issue in raw_issues),
            )
            prompt = build_correction_prompt(
                initial_prompt,
                outcome=correction_outcome,
                invalid_output=previous_output,
            )
        if (
            prompt.prompt_version != prepared.prompt_version
            or prompt.prompt_hash != prepared.prompt_hash
            or prompt.result_schema_version != prepared.result_schema_version
            or prompt.result_schema_hash != prepared.result_schema_hash
            or prompt.rubric_hash != prepared.rubric_hash
        ):
            raise RuntimeError("评分批次快照与当前评分契约不一致")
        profile = prepared.provider_snapshot.model_profile
        if profile.capabilities.model != prepared.model:
            raise RuntimeError("评分批次模型与能力快照不一致")
        api_key = self._cipher.decrypt(
            EncryptedApiKey(
                ciphertext=prepared.encrypted_api_key,
                nonce=prepared.api_key_nonce,
            ),
            provider_id=prepared.provider_config_id,
        )
        provider_request = ProviderGradeRequest(
            provider_config_id=prepared.provider_config_id,
            config_version=prepared.provider_config_version,
            provider_type=prepared.provider_snapshot.provider_type,
            base_url=prepared.provider_snapshot.base_url,
            api_key=SecretStr(api_key),
            model=prepared.model,
            timeout_seconds=prepared.provider_snapshot.timeout_seconds,
            max_output_tokens=profile.grading_max_output_tokens,
            capabilities=profile.capabilities,
            result_schema_json=canonical_json_bytes(prepared.result_schema),
            prompt=prompt,
        )
        claim = await self._repository.claim_attempt(prepared, prompt.call_hash)
        if claim is None:
            return "duplicate"
        if claim.request_hash != prompt.call_hash:
            raise RuntimeError("数据库 claim 返回了不同评分请求")

        adapter = self._adapters.require(prepared.provider_snapshot.provider_type)
        try:
            provider_result = await adapter.grade(provider_request)
        except ProviderUrlError:
            await self._repository.finish_failure(
                claim,
                GradingAttemptFailure(
                    action="failed",
                    error_code="provider_base_url_unavailable",
                    error_details={"reason": "url_policy_rejected"},
                    provider_call_state="not_sent",
                ),
            )
            return "failed"
        except ProviderAdapterError as error:
            if error.retryable and error.retry_safety == "safe":
                provider_failure_action: Literal["retry", "needs_review", "failed"] = (
                    "retry" if claim.call_sequence <= self._max_provider_retries else "needs_review"
                )
            elif error.retry_safety == "unknown":
                provider_failure_action = "needs_review"
            else:
                provider_failure_action = "failed"
            response_object_key: str | None = None
            response_object_sha256: bytes | None = None
            provider_request_id: str | None = None
            if error.response is not None:
                response_object_key = build_provider_response_object_key(
                    prepared,
                    claim.attempt_id,
                )
                response_object_sha256 = hashlib.sha256(error.response.raw_body).digest()
                provider_request_id = next(
                    (
                        error.response.headers[name]
                        for name in ("x-request-id", "openai-request-id", "request-id")
                        if name in error.response.headers
                    ),
                    None,
                )
                error_envelope = canonical_json_bytes(
                    {
                        "schema_version": "provider-response.v1",
                        "attempt_id": claim.attempt_id,
                        "request_hash": claim.request_hash.hex(),
                        "received_at": self._now().isoformat(),
                        "error_code": error.code,
                        "status_code": error.response.status_code,
                        "headers": error.response.headers,
                        "raw_response_base64": base64.b64encode(error.response.raw_body).decode(
                            "ascii"
                        ),
                        "raw_response_sha256": response_object_sha256.hex(),
                    }
                )
                await self._storage.put_json_once(response_object_key, error_envelope)
            await self._repository.finish_failure(
                claim,
                GradingAttemptFailure(
                    action=provider_failure_action,
                    retry_delay_seconds=(
                        min(60, 5 * 2 ** (claim.call_sequence - 1))
                        if provider_failure_action == "retry"
                        else 0
                    ),
                    error_code=error.code,
                    error_details={
                        "retryable": error.retryable,
                        "retry_safety": error.retry_safety,
                    },
                    provider_call_state=(
                        "response_received"
                        if error.response is not None
                        else "not_sent"
                        if error.retry_safety == "safe"
                        else "ambiguous"
                    ),
                    provider_request_id=provider_request_id,
                    response_object_key=response_object_key,
                    response_object_sha256=response_object_sha256,
                ),
            )
            return (
                "retry_scheduled" if provider_failure_action == "retry" else provider_failure_action
            )
        response_object_key = build_provider_response_object_key(prepared, claim.attempt_id)
        response_envelope = canonical_json_bytes(
            {
                "schema_version": "provider-response.v1",
                "attempt_id": claim.attempt_id,
                "request_hash": claim.request_hash.hex(),
                "received_at": self._now().isoformat(),
                "provider_type": provider_result.provider_type.value,
                "requested_model": provider_result.requested_model,
                "reported_model": provider_result.reported_model,
                "request_id": provider_result.request_id,
                "finish_reason": provider_result.finish_reason,
                "output_text": provider_result.output_text,
                "usage": provider_result.usage,
                "estimated_cost": provider_result.estimated_cost,
                "raw_response_base64": base64.b64encode(provider_result.raw_response).decode(
                    "ascii"
                ),
                "raw_response_sha256": provider_result.raw_response_sha256.hex(),
                "sent_schema_sha256": provider_result.sent_schema_sha256.hex(),
            }
        )
        await self._storage.put_json_once(response_object_key, response_envelope)
        try:
            raw_result = json.loads(provider_result.output_text)
        except json.JSONDecodeError:
            raw_result = None
        outcome = assess_grade_response(raw_result, grade_request, prompt=prompt)
        if outcome.status != "accepted" or outcome.result is None:
            validation_action: Literal["retry", "needs_review"] = (
                "retry" if outcome.status == "correction_required" else "needs_review"
            )
            await self._repository.finish_failure(
                claim,
                GradingAttemptFailure(
                    action=validation_action,
                    error_code=outcome.code or "grade_output_invalid",
                    error_details={
                        "issues": [issue.model_dump(mode="json") for issue in outcome.issues]
                    },
                    provider_call_state="response_received",
                    provider_result=provider_result,
                    response_object_key=response_object_key,
                    response_object_sha256=provider_result.raw_response_sha256,
                ),
            )
            return "retry_scheduled" if validation_action == "retry" else "needs_review"
        await self._repository.finish_success(
            claim,
            GradingAttemptCompletion(
                validated_result=outcome.result,
                provider_result=provider_result,
                response_object_key=response_object_key,
                response_object_sha256=provider_result.raw_response_sha256,
            ),
        )
        return "completed"
