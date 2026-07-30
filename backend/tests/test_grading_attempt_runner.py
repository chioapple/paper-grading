"""阶段十单篇评分、持久化和重复投递行为测试。"""

import asyncio
import base64
import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import SecretStr

from app.domain.enums import ProviderType
from app.domain.grading import GradeResult, canonical_json_bytes
from app.grading.prompt import build_grading_contract_snapshot
from app.providers.base import (
    ProviderAdapterError,
    ProviderCredentialValidation,
    ProviderGradeRequest,
    ProviderGradeResult,
    ProviderHttpResponse,
    ProviderModelCapabilities,
    ProviderModelProfile,
    ProviderTokenUsage,
)
from app.providers.connection import ProviderUrlError
from app.providers.registry import ProviderAdapterRegistry
from app.security.encryption import ApiKeyCipher
from app.workers.models import GradingProviderSnapshot
from app.workers.tasks import (
    GradingAttemptClaim,
    GradingAttemptCompletion,
    GradingAttemptFailure,
    GradingAttemptRunner,
    GradingItemPreparation,
)
from tests.test_grading_contract import build_request, valid_model_output

OWNER_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("22222222-2222-2222-2222-222222222222")
ITEM_ID = UUID("33333333-3333-3333-3333-333333333333")
ATTEMPT_ID = UUID("44444444-4444-4444-4444-444444444444")
PROVIDER_ID = UUID("55555555-5555-5555-5555-555555555555")


class AttemptRepositoryBase:
    """单路径测试不允许意外进入另一种收口分支。"""

    async def finish_success(
        self,
        claim: GradingAttemptClaim,
        completion: GradingAttemptCompletion,
    ) -> None:
        raise AssertionError((claim, completion))

    async def finish_failure(
        self,
        claim: GradingAttemptClaim,
        failure: GradingAttemptFailure,
    ) -> None:
        raise AssertionError((claim, failure))


def build_preparation(cipher: ApiKeyCipher) -> GradingItemPreparation:
    request = build_request()
    encrypted = cipher.encrypt("stage-ten-provider-key", provider_id=PROVIDER_ID)
    profile = ProviderModelProfile(
        capabilities=ProviderModelCapabilities(
            capability_version="admin-confirmed-2026-07-16",
            model="deepseek-v4-pro",
            context_window_tokens=1_000_000,
            max_output_tokens=393_216,
            structured_output="json_object",
            schema_dialect="canonical",
            sampling_policy="temperature_zero",
            thinking_policy="disabled",
            output_token_parameter="max_tokens",
            supports_model_listing=True,
            pricing=None,
        ),
        grading_max_output_tokens=8192,
    )
    provider_snapshot = GradingProviderSnapshot(
        provider_type="deepseek",
        base_url="https://api.deepseek.com",
        timeout_seconds=Decimal("60"),
        max_concurrency=2,
        model_profile=profile,
    )
    contract = build_grading_contract_snapshot(request.rubric)
    return GradingItemPreparation(
        owner_id=OWNER_ID,
        job_id=JOB_ID,
        item_id=ITEM_ID,
        dispatch_version=1,
        submission_id=request.submission_id,
        extracted_object_key="teachers/owner/submission/document-blocks.v1.json",
        assignment_id=request.assignment_id,
        assignment_title=request.assignment_title,
        assignment_instructions=request.assignment_instructions,
        rubric_version_id=request.rubric_version_id,
        rubric_version=request.rubric_version,
        rubric=request.rubric,
        provider_config_id=PROVIDER_ID,
        provider_config_version=1,
        encrypted_api_key=encrypted.ciphertext,
        api_key_nonce=encrypted.nonce,
        model="deepseek-v4-pro",
        provider_snapshot=provider_snapshot,
        prompt_version=contract.prompt_version,
        prompt_hash=contract.prompt_hash,
        result_schema_version=contract.result_schema_version,
        result_schema=contract.result_schema,
        result_schema_hash=contract.result_schema_hash,
        rubric_hash=contract.rubric_hash,
        attempt_kind="initial",
        parent_attempt_id=None,
        previous_response_object_key=None,
        previous_error_details=None,
    )


def test_duplicate_delivery_calls_the_provider_once_and_persists_one_attempt() -> None:
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode())
    preparation = build_preparation(cipher)
    grade_request = build_request()
    stored = {
        preparation.extracted_object_key: grade_request.document.model_dump_json().encode("utf-8")
    }

    class Repository(AttemptRepositoryBase):
        claimed = False
        completion: GradingAttemptCompletion | None = None

        async def prepare_item(
            self,
            item_id: UUID,
            dispatch_version: int,
        ) -> GradingItemPreparation | None:
            assert item_id == ITEM_ID
            assert dispatch_version == 1
            return None if self.claimed else preparation

        async def claim_attempt(
            self,
            prepared: GradingItemPreparation,
            request_hash: bytes,
        ) -> GradingAttemptClaim | None:
            if self.claimed:
                return None
            self.claimed = True
            return GradingAttemptClaim(
                attempt_id=ATTEMPT_ID,
                attempt_number=1,
                scoring_round=1,
                call_sequence=1,
                lease_token=UUID("66666666-6666-6666-6666-666666666666"),
                request_hash=request_hash,
            )

        async def finish_success(
            self,
            claim: GradingAttemptClaim,
            completion: GradingAttemptCompletion,
        ) -> None:
            assert claim.attempt_id == ATTEMPT_ID
            self.completion = completion

    class Storage:
        async def get_json(self, key: str) -> bytes:
            return stored[key]

        async def put_json_once(self, key: str, content: bytes) -> None:
            assert key not in stored
            stored[key] = content

    class Adapter:
        calls = 0

        async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
            self.calls += 1
            assert request.api_key == SecretStr("stage-ten-provider-key")
            raw = b'{"id":"response-stage-ten"}'
            return ProviderGradeResult(
                provider_type=ProviderType.DEEPSEEK,
                requested_model=request.model,
                reported_model=request.model,
                request_id="response-stage-ten",
                output_text=canonical_json_bytes(valid_model_output()).decode("utf-8"),
                usage=ProviderTokenUsage(
                    input_tokens=100,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    output_tokens=50,
                    reasoning_tokens=0,
                    total_tokens=150,
                ),
                estimated_cost=None,
                raw_response=raw,
                raw_response_sha256=hashlib.sha256(raw).digest(),
                sent_schema_sha256=request.prompt.result_schema_hash,
            )

        async def validate_credentials(
            self,
            request: ProviderGradeRequest,
        ) -> ProviderCredentialValidation:
            raise AssertionError(request)

    repository = Repository()
    adapter = Adapter()
    runner = GradingAttemptRunner(
        repository=repository,
        storage=Storage(),
        adapters=ProviderAdapterRegistry({ProviderType.DEEPSEEK: adapter}),
        cipher=cipher,
        now=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )

    first = asyncio.run(runner.run(ITEM_ID, 1))
    second = asyncio.run(runner.run(ITEM_ID, 1))

    assert first == "completed"
    assert second == "duplicate"
    assert adapter.calls == 1
    assert repository.completion is not None
    assert repository.completion.validated_result.total_score == Decimal("7")
    assert repository.completion.provider_result.request_id == "response-stage-ten"
    assert repository.completion.response_object_key.endswith("/provider-response.v1.json")
    assert GradeResult.model_validate(valid_model_output())


def test_unknown_network_outcome_needs_review_and_is_never_called_twice() -> None:
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode())
    preparation = build_preparation(cipher)
    grade_request = build_request()

    class Repository(AttemptRepositoryBase):
        claimed = False
        failure: GradingAttemptFailure | None = None

        async def prepare_item(
            self,
            item_id: UUID,
            dispatch_version: int,
        ) -> GradingItemPreparation | None:
            return None if self.claimed else preparation

        async def claim_attempt(
            self,
            prepared: GradingItemPreparation,
            request_hash: bytes,
        ) -> GradingAttemptClaim | None:
            self.claimed = True
            return GradingAttemptClaim(
                attempt_id=ATTEMPT_ID,
                attempt_number=1,
                scoring_round=1,
                call_sequence=1,
                lease_token=UUID("66666666-6666-6666-6666-666666666666"),
                request_hash=request_hash,
            )

        async def finish_failure(
            self,
            claim: GradingAttemptClaim,
            failure: GradingAttemptFailure,
        ) -> None:
            self.failure = failure

    class Storage:
        async def get_json(self, key: str) -> bytes:
            return grade_request.document.model_dump_json().encode()

        async def put_json_once(self, key: str, content: bytes) -> None:
            raise AssertionError((key, content))

    class Adapter:
        calls = 0

        async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
            self.calls += 1
            raise ProviderAdapterError(
                "provider_timeout",
                "供应商评分请求超时",
                retryable=True,
            )

        async def validate_credentials(
            self,
            request: ProviderGradeRequest,
        ) -> ProviderCredentialValidation:
            raise AssertionError(request)

    repository = Repository()
    adapter = Adapter()
    runner = GradingAttemptRunner(
        repository=repository,
        storage=Storage(),
        adapters=ProviderAdapterRegistry({ProviderType.DEEPSEEK: adapter}),
        cipher=cipher,
        now=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )

    first = asyncio.run(runner.run(ITEM_ID, 1))
    second = asyncio.run(runner.run(ITEM_ID, 1))

    assert first == "needs_review"
    assert second == "duplicate"
    assert adapter.calls == 1
    assert repository.failure is not None
    assert repository.failure.provider_call_state == "ambiguous"
    assert repository.failure.action == "needs_review"


def test_url_policy_rejection_after_claim_is_persisted_as_not_sent_failure() -> None:
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode())
    preparation = build_preparation(cipher)
    grade_request = build_request()

    class Repository(AttemptRepositoryBase):
        failure: GradingAttemptFailure | None = None

        async def prepare_item(
            self,
            item_id: UUID,
            dispatch_version: int,
        ) -> GradingItemPreparation | None:
            return preparation

        async def claim_attempt(
            self,
            prepared: GradingItemPreparation,
            request_hash: bytes,
        ) -> GradingAttemptClaim | None:
            return GradingAttemptClaim(
                attempt_id=ATTEMPT_ID,
                attempt_number=1,
                scoring_round=1,
                call_sequence=1,
                lease_token=UUID("66666666-6666-6666-6666-666666666666"),
                request_hash=request_hash,
            )

        async def finish_failure(
            self,
            claim: GradingAttemptClaim,
            failure: GradingAttemptFailure,
        ) -> None:
            self.failure = failure

    class Storage:
        async def get_json(self, key: str) -> bytes:
            return grade_request.document.model_dump_json().encode()

        async def put_json_once(self, key: str, content: bytes) -> None:
            raise AssertionError((key, content))

    class Adapter:
        async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
            raise ProviderUrlError("Base URL 只能解析到公网地址")

        async def validate_credentials(
            self,
            request: ProviderGradeRequest,
        ) -> ProviderCredentialValidation:
            raise AssertionError(request)

    repository = Repository()
    result = asyncio.run(
        GradingAttemptRunner(
            repository=repository,
            storage=Storage(),
            adapters=ProviderAdapterRegistry({ProviderType.DEEPSEEK: Adapter()}),
            cipher=cipher,
            now=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        ).run(ITEM_ID, 1)
    )

    assert result == "failed"
    assert repository.failure is not None
    assert repository.failure.action == "failed"
    assert repository.failure.error_code == "provider_base_url_unavailable"
    assert repository.failure.provider_call_state == "not_sent"


def test_explicit_rate_limit_response_retries_the_same_model_snapshot() -> None:
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode())
    preparation = build_preparation(cipher)
    grade_request = build_request()
    stored = {preparation.extracted_object_key: grade_request.document.model_dump_json().encode()}

    class Repository(AttemptRepositoryBase):
        failure: GradingAttemptFailure | None = None

        async def prepare_item(
            self,
            item_id: UUID,
            dispatch_version: int,
        ) -> GradingItemPreparation | None:
            return preparation

        async def claim_attempt(
            self,
            prepared: GradingItemPreparation,
            request_hash: bytes,
        ) -> GradingAttemptClaim | None:
            return GradingAttemptClaim(
                attempt_id=ATTEMPT_ID,
                attempt_number=1,
                scoring_round=1,
                call_sequence=1,
                lease_token=UUID("66666666-6666-6666-6666-666666666666"),
                request_hash=request_hash,
            )

        async def finish_failure(
            self,
            claim: GradingAttemptClaim,
            failure: GradingAttemptFailure,
        ) -> None:
            self.failure = failure

    class Storage:
        async def get_json(self, key: str) -> bytes:
            return stored[key]

        async def put_json_once(self, key: str, content: bytes) -> None:
            stored[key] = content

    class Adapter:
        async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
            assert request.model == "deepseek-v4-pro"
            assert request.config_version == 1
            raise ProviderAdapterError(
                "provider_rate_limited",
                "供应商暂时限制评分请求",
                retryable=True,
                retry_safety="safe",
                response=ProviderHttpResponse(
                    status_code=429,
                    json_body={"error": "rate_limited"},
                    raw_body=b'{"error":"rate_limited"}',
                    headers={"x-request-id": "rate-limit-request"},
                ),
            )

        async def validate_credentials(
            self,
            request: ProviderGradeRequest,
        ) -> ProviderCredentialValidation:
            raise AssertionError(request)

    repository = Repository()
    result = asyncio.run(
        GradingAttemptRunner(
            repository=repository,
            storage=Storage(),
            adapters=ProviderAdapterRegistry({ProviderType.DEEPSEEK: Adapter()}),
            cipher=cipher,
            now=lambda: datetime(2026, 7, 16, tzinfo=UTC),
        ).run(ITEM_ID, 1)
    )

    assert result == "retry_scheduled"
    assert repository.failure is not None
    assert repository.failure.action == "retry"
    assert repository.failure.retry_delay_seconds == 5
    assert repository.failure.provider_call_state == "response_received"
    assert repository.failure.provider_request_id == "rate-limit-request"
    assert repository.failure.response_object_key in stored


def test_first_invalid_output_uses_the_same_snapshot_for_one_correction() -> None:
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode())
    initial = build_preparation(cipher)
    grade_request = build_request()
    stored = {
        initial.extracted_object_key: grade_request.document.model_dump_json().encode("utf-8")
    }

    class Repository(AttemptRepositoryBase):
        phase = 0
        failures: list[GradingAttemptFailure] = []
        completion: GradingAttemptCompletion | None = None

        async def prepare_item(
            self,
            item_id: UUID,
            dispatch_version: int,
        ) -> GradingItemPreparation | None:
            if self.phase == 0:
                return initial
            if self.phase == 1:
                failure = self.failures[0]
                return initial.model_copy(
                    update={
                        "attempt_kind": "correction",
                        "parent_attempt_id": ATTEMPT_ID,
                        "previous_response_object_key": failure.response_object_key,
                        "previous_error_details": failure.error_details,
                    }
                )
            return None

        async def claim_attempt(
            self,
            prepared: GradingItemPreparation,
            request_hash: bytes,
        ) -> GradingAttemptClaim | None:
            return GradingAttemptClaim(
                attempt_id=(ATTEMPT_ID if self.phase == 0 else UUID(int=ATTEMPT_ID.int + 1)),
                attempt_number=self.phase + 1,
                scoring_round=1,
                call_sequence=self.phase + 1,
                lease_token=UUID(int=UUID("66666666-6666-6666-6666-666666666666").int + self.phase),
                request_hash=request_hash,
            )

        async def finish_failure(
            self,
            claim: GradingAttemptClaim,
            failure: GradingAttemptFailure,
        ) -> None:
            assert failure.action == "retry"
            assert failure.error_code == "grade_output_correction_required"
            self.failures.append(failure)
            self.phase = 1

        async def finish_success(
            self,
            claim: GradingAttemptClaim,
            completion: GradingAttemptCompletion,
        ) -> None:
            self.completion = completion
            self.phase = 2

    class Storage:
        async def get_json(self, key: str) -> bytes:
            return stored[key]

        async def put_json_once(self, key: str, content: bytes) -> None:
            stored[key] = content

    class Adapter:
        calls = 0
        message_counts: list[int] = []
        snapshot_hashes: list[bytes] = []

        async def grade(self, request: ProviderGradeRequest) -> ProviderGradeResult:
            self.calls += 1
            self.message_counts.append(len(request.prompt.messages))
            self.snapshot_hashes.append(request.snapshot_hash())
            raw = f'{{"call":{self.calls}}}'.encode()
            output = (
                "{}" if self.calls == 1 else canonical_json_bytes(valid_model_output()).decode()
            )
            return ProviderGradeResult(
                provider_type=ProviderType.DEEPSEEK,
                requested_model=request.model,
                reported_model=request.model,
                request_id=f"response-stage-ten-{self.calls}",
                output_text=output,
                usage=ProviderTokenUsage(
                    input_tokens=100,
                    cached_input_tokens=0,
                    cache_write_input_tokens=0,
                    output_tokens=50,
                    reasoning_tokens=0,
                    total_tokens=150,
                ),
                estimated_cost=None,
                raw_response=raw,
                raw_response_sha256=hashlib.sha256(raw).digest(),
                sent_schema_sha256=request.prompt.result_schema_hash,
            )

        async def validate_credentials(
            self,
            request: ProviderGradeRequest,
        ) -> ProviderCredentialValidation:
            raise AssertionError(request)

    repository = Repository()
    adapter = Adapter()
    runner = GradingAttemptRunner(
        repository=repository,
        storage=Storage(),
        adapters=ProviderAdapterRegistry({ProviderType.DEEPSEEK: adapter}),
        cipher=cipher,
        now=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )

    first = asyncio.run(runner.run(ITEM_ID, 1))
    second = asyncio.run(runner.run(ITEM_ID, 1))

    assert first == "retry_scheduled"
    assert second == "completed"
    assert adapter.message_counts == [2, 3]
    assert adapter.snapshot_hashes[0] == adapter.snapshot_hashes[1]
    assert repository.completion is not None
