"""阶段十一教师复核服务的公共行为测试。"""

import asyncio
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.grading import DimensionResult, EvidenceQuote
from app.domain.rubric import (
    RubricBand,
    RubricDeduction,
    RubricDimension,
    StructuredRubric,
)
from app.parsing.models import DocumentBlock, ParsedDocument, PdfTextBlockLocator
from app.reviews.models import (
    ReviewAttemptView,
    ReviewConfirmationRef,
    ReviewConfirmationResult,
    ReviewCriterionInput,
    ReviewDeductionInput,
    ReviewDraftData,
    ReviewDraftInput,
    ReviewDraftView,
    ReviewEvidenceInput,
    ReviewRegradeTarget,
    ReviewTarget,
)
from app.reviews.service import (
    ReviewConflictError,
    ReviewService,
    ReviewStateError,
    ReviewValidationError,
)
from app.workers.models import GradingJobView

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
ITEM_ID = UUID("33333333-3333-4333-8333-333333333333")
SUBMISSION_ID = UUID("44444444-4444-4444-8444-444444444444")
ASSIGNMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
RUBRIC_ID = UUID("66666666-6666-4666-8666-666666666666")
ATTEMPT_ID = UUID("77777777-7777-4777-8777-777777777777")
REVIEW_ID = UUID("88888888-8888-4888-8888-888888888888")


def rubric() -> StructuredRubric:
    return StructuredRubric(
        schema_version=1,
        total_score=Decimal("10"),
        score_step=Decimal("1"),
        dimensions=(
            RubricDimension(
                id="argument",
                name="Argument",
                description="Quality of the argument.",
                max_score=Decimal("5"),
                bands=(
                    RubricBand(
                        label="None",
                        min_score=Decimal("0"),
                        max_score=Decimal("0"),
                        description="No argument.",
                    ),
                    RubricBand(
                        label="Developing",
                        min_score=Decimal("1"),
                        max_score=Decimal("3"),
                        description="Partly supported.",
                    ),
                    RubricBand(
                        label="Strong",
                        min_score=Decimal("4"),
                        max_score=Decimal("5"),
                        description="Well supported.",
                    ),
                ),
                evidence_requirements=("Quote the claim.",),
            ),
            RubricDimension(
                id="language",
                name="Language",
                description="Clarity of English.",
                max_score=Decimal("5"),
                bands=(
                    RubricBand(
                        label="None",
                        min_score=Decimal("0"),
                        max_score=Decimal("0"),
                        description="No assessable language.",
                    ),
                    RubricBand(
                        label="Developing",
                        min_score=Decimal("1"),
                        max_score=Decimal("3"),
                        description="Uneven clarity.",
                    ),
                    RubricBand(
                        label="Strong",
                        min_score=Decimal("4"),
                        max_score=Decimal("5"),
                        description="Consistently clear.",
                    ),
                ),
                evidence_requirements=("Quote representative wording.",),
            ),
        ),
        deductions=(
            RubricDeduction(
                id="missing_title",
                name="Missing title",
                description="Deduct one point when the title is absent.",
                points=Decimal("1"),
            ),
        ),
    )


def document() -> ParsedDocument:
    return ParsedDocument(
        media_type="application/pdf",
        page_count=1,
        character_count=112,
        blocks=(
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
        ),
    )


def attempt() -> ReviewAttemptView:
    return ReviewAttemptView(
        id=ATTEMPT_ID,
        attempt_number=1,
        scoring_round=1,
        model="deepseek-v4-pro",
        subtotal=Decimal("8"),
        deduction_total=Decimal("1"),
        total_score=Decimal("7"),
        dimensions=(
            DimensionResult(
                dimension_id="argument",
                score="4",
                reason="The claim is clear.",
                evidence=(EvidenceQuote(block_id="b000001", quote="it reduces traffic"),),
                revision_suggestions=("Explain the causal link.",),
            ),
            DimensionResult(
                dimension_id="language",
                score="4",
                reason="The sentences are clear.",
                evidence=(
                    EvidenceQuote(
                        block_id="b000002",
                        quote="cities cleaner and easier to reach",
                    ),
                ),
                revision_suggestions=("Vary sentence openings.",),
            ),
        ),
        deductions=(
            {
                "deduction_id": "missing_title",
                "applied": True,
                "reason": "The title is absent.",
                "evidence": [],
            },
        ),
        overall_feedback="A clear response with room for fuller explanation.",
    )


def target() -> ReviewTarget:
    return ReviewTarget(
        owner_id=OWNER_ID,
        job_id=JOB_ID,
        item_id=ITEM_ID,
        item_status="needs_review",
        assignment_id=ASSIGNMENT_ID,
        assignment_title="Argumentative essay",
        assignment_instructions="Discuss whether public transport should be free.",
        rubric_version_id=RUBRIC_ID,
        rubric_version=1,
        rubric=rubric(),
        submission_id=SUBMISSION_ID,
        original_filename="essay-01.pdf",
        submission_status="ready",
        extracted_object_key="private/parsed.json",
        attempt=attempt(),
        draft=None,
    )


def unchanged_payload() -> ReviewDraftInput:
    return ReviewDraftInput(
        attempt_id=ATTEMPT_ID,
        criteria=(
            ReviewCriterionInput(
                dimension_id="argument",
                score="4",
                reason="The claim is clear.",
                revision_suggestions=("Explain the causal link.",),
            ),
            ReviewCriterionInput(
                dimension_id="language",
                score="4",
                reason="The sentences are clear.",
                revision_suggestions=("Vary sentence openings.",),
            ),
        ),
        deductions=(
            ReviewDeductionInput(
                deduction_id="missing_title",
                applied=True,
                reason="The title is absent.",
            ),
        ),
        evidence=(
            ReviewEvidenceInput(
                target_type="dimension",
                target_id="argument",
                block_id="b000001",
                quote="it reduces traffic",
            ),
            ReviewEvidenceInput(
                target_type="dimension",
                target_id="language",
                block_id="b000002",
                quote="cities cleaner and easier to reach",
            ),
        ),
        overall_feedback="A clear response with room for fuller explanation.",
        change_reason=None,
    )


def test_teacher_review_narrative_fields_must_remain_english() -> None:
    payload = unchanged_payload().model_dump(mode="json")
    payload["overall_feedback"] = "这不是英文总体反馈。"

    with pytest.raises(ValidationError, match="必须使用英文"):
        ReviewDraftInput.model_validate(payload)


def test_review_detail_rejects_non_english_ai_overall_feedback() -> None:
    payload = attempt().model_dump(mode="json")
    payload["overall_feedback"] = "这不是英文总体反馈。"

    with pytest.raises(ValidationError, match="必须使用英文"):
        ReviewAttemptView.model_validate(payload)


def saved_draft(*, status: Literal["draft", "confirmed"] = "draft") -> ReviewDraftView:
    payload = unchanged_payload()
    return ReviewDraftView(
        id=REVIEW_ID,
        attempt_id=ATTEMPT_ID,
        revision_number=1,
        status=status,
        criteria=payload.criteria,
        deductions=payload.deductions,
        evidence=payload.evidence,
        overall_feedback=payload.overall_feedback,
        change_reason=payload.change_reason,
        subtotal=Decimal("8"),
        deduction_total=Decimal("1"),
        final_score=Decimal("7"),
        confirmed_at=None,
    )


def test_save_draft_recalculates_total_without_overwriting_ai_attempt() -> None:
    saved: list[ReviewDraftData] = []

    class Repository:
        async def get_target(self, owner_id: UUID, item_id: UUID) -> ReviewTarget | None:
            assert (owner_id, item_id) == (OWNER_ID, ITEM_ID)
            return target()

        async def save_draft(
            self,
            owner_id: UUID,
            item_id: UUID,
            data: ReviewDraftData,
        ) -> ReviewDraftView:
            assert (owner_id, item_id) == (OWNER_ID, ITEM_ID)
            saved.append(data)
            return ReviewDraftView(
                id=REVIEW_ID,
                attempt_id=ATTEMPT_ID,
                revision_number=1,
                status="draft",
                criteria=data.criteria,
                deductions=data.deductions,
                evidence=data.evidence,
                overall_feedback=data.overall_feedback,
                change_reason=data.change_reason,
                subtotal=data.subtotal,
                deduction_total=data.deduction_total,
                final_score=data.final_score,
                confirmed_at=None,
            )

    class Storage:
        async def get_json(self, key: str) -> bytes:
            assert key == "private/parsed.json"
            return document().model_dump_json().encode()

    original_attempt = attempt()
    result = asyncio.run(
        ReviewService(
            repository=Repository(),  # type: ignore[arg-type]
            storage=Storage(),
        ).save_draft(
            OWNER_ID,
            ITEM_ID,
            unchanged_payload(),
        )
    )

    assert result.final_score == Decimal("7")
    assert saved[0].deduction_total == Decimal("1")
    assert target().attempt == original_attempt


def test_changed_ai_result_requires_teacher_reason() -> None:
    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target()

        async def save_draft(self, *_args: object) -> ReviewDraftView:
            raise AssertionError("无修改原因时不能写草稿")

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    changed = unchanged_payload().model_copy(
        update={
            "criteria": (
                unchanged_payload().criteria[0].model_copy(update={"score": Decimal("5")}),
                unchanged_payload().criteria[1],
            )
        }
    )

    try:
        asyncio.run(
            ReviewService(
                repository=Repository(),  # type: ignore[arg-type]
                storage=Storage(),
            ).save_draft(
                OWNER_ID,
                ITEM_ID,
                changed,
            )
        )
    except ReviewValidationError as error:
        assert error.code == "review_change_reason_required"
    else:
        raise AssertionError("修改 AI 结果必须明确失败")


def test_teacher_evidence_must_exist_verbatim_in_named_block() -> None:
    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target()

        async def save_draft(self, *_args: object) -> ReviewDraftView:
            raise AssertionError("虚假证据不能写草稿")

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    invalid = unchanged_payload().model_copy(
        update={
            "evidence": (
                unchanged_payload()
                .evidence[0]
                .model_copy(update={"quote": "text that is not in the block"}),
                unchanged_payload().evidence[1],
            )
        }
    )

    try:
        asyncio.run(
            ReviewService(
                repository=Repository(),  # type: ignore[arg-type]
                storage=Storage(),
            ).save_draft(
                OWNER_ID,
                ITEM_ID,
                invalid,
            )
        )
    except ReviewValidationError as error:
        assert error.code == "review_evidence_quote_mismatch"
    else:
        raise AssertionError("引文不匹配必须明确失败")


def test_new_attempt_cannot_reuse_an_old_draft_payload() -> None:
    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target().model_copy(
                update={
                    "attempt": attempt().model_copy(
                        update={
                            "id": UUID("99999999-9999-4999-8999-999999999999"),
                            "attempt_number": 2,
                            "scoring_round": 2,
                        }
                    )
                }
            )

        async def save_draft(self, *_args: object) -> ReviewDraftView:
            raise AssertionError("旧 attempt 草稿不能写入")

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    try:
        asyncio.run(
            ReviewService(
                repository=Repository(),  # type: ignore[arg-type]
                storage=Storage(),
            ).save_draft(
                OWNER_ID,
                ITEM_ID,
                unchanged_payload(),
            )
        )
    except ReviewConflictError:
        pass
    else:
        raise AssertionError("旧 attempt 草稿必须明确冲突")


def test_review_detail_excludes_private_execution_and_storage_metadata() -> None:
    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target()

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    result = asyncio.run(
        ReviewService(
            repository=Repository(),  # type: ignore[arg-type]
            storage=Storage(),
        ).get_detail(OWNER_ID, ITEM_ID)
    ).model_dump(mode="json")
    serialized = str(result)

    for forbidden in (
        "extracted_object_key",
        "raw_response",
        "provider_request_id",
        "input_tokens",
        "estimated_cost",
        "api_key",
    ):
        assert forbidden not in serialized


def test_single_confirmation_saves_and_confirms_in_one_repository_call() -> None:
    calls: list[str] = []

    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target()

        async def save_and_confirm(
            self,
            owner_id: UUID,
            job_id: UUID,
            item_id: UUID,
            data: ReviewDraftData,
        ) -> ReviewConfirmationResult:
            assert (owner_id, job_id, item_id) == (OWNER_ID, JOB_ID, ITEM_ID)
            assert data.final_score == Decimal("7")
            calls.append("save_and_confirm")
            return ReviewConfirmationResult(
                reviews=(saved_draft(status="confirmed"),),
                completed_job_ids=(JOB_ID,),
            )

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    result = asyncio.run(
        ReviewService(
            repository=Repository(),  # type: ignore[arg-type]
            storage=Storage(),
        ).confirm(
            OWNER_ID,
            JOB_ID,
            ITEM_ID,
            unchanged_payload(),
        )
    )

    assert result.reviews[0].status == "confirmed"
    assert calls == ["save_and_confirm"]


def test_batch_confirmation_validates_every_saved_draft_before_writing() -> None:
    invalid_draft = saved_draft().model_copy(
        update={
            "evidence": (
                unchanged_payload().evidence[0].model_copy(update={"quote": "not present"}),
                unchanged_payload().evidence[1],
            )
        }
    )

    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target().model_copy(update={"draft": invalid_draft})

        async def confirm_reviews(self, *_args: object) -> ReviewConfirmationResult:
            raise AssertionError("批量中有坏数据时不得进入确认事务")

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    reference = ReviewConfirmationRef(
        item_id=ITEM_ID,
        review_id=REVIEW_ID,
        revision_number=1,
    )
    try:
        asyncio.run(
            ReviewService(
                repository=Repository(),  # type: ignore[arg-type]
                storage=Storage(),
            ).confirm_batch(
                OWNER_ID,
                JOB_ID,
                (reference,),
            )
        )
    except ReviewValidationError as error:
        assert error.code == "review_evidence_quote_mismatch"
    else:
        raise AssertionError("坏草稿必须让整个批量确认失败")


def test_confirmed_review_blocks_original_model_regrade() -> None:
    class Repository:
        async def get_regrade_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewRegradeTarget:
            return ReviewRegradeTarget(
                job_id=JOB_ID,
                item_id=ITEM_ID,
                item_status="completed",
                has_confirmed_review=True,
            )

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    class Regrader:
        async def retry_item(
            self, _owner_id: UUID, _job_id: UUID, _item_id: UUID
        ) -> GradingJobView:
            raise AssertionError("确认后不得再次投递模型")

    try:
        asyncio.run(
            ReviewService(
                repository=Repository(),  # type: ignore[arg-type]
                storage=Storage(),
                regrader=Regrader(),
            ).regrade(OWNER_ID, JOB_ID, ITEM_ID)
        )
    except ReviewStateError:
        pass
    else:
        raise AssertionError("确认后的复核必须阻止重评")


def test_unconfirmed_review_uses_stage_ten_regrade_entry() -> None:
    calls: list[tuple[UUID, UUID, UUID]] = []

    class Repository:
        async def get_regrade_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewRegradeTarget:
            return ReviewRegradeTarget(
                job_id=JOB_ID,
                item_id=ITEM_ID,
                item_status="needs_review",
                has_confirmed_review=False,
            )

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    class Regrader:
        async def retry_item(self, owner_id: UUID, job_id: UUID, item_id: UUID) -> GradingJobView:
            calls.append((owner_id, job_id, item_id))
            return cast(GradingJobView, object())

    asyncio.run(
        ReviewService(
            repository=Repository(),  # type: ignore[arg-type]
            storage=Storage(),
            regrader=Regrader(),
        ).regrade(OWNER_ID, JOB_ID, ITEM_ID)
    )

    assert calls == [(OWNER_ID, JOB_ID, ITEM_ID)]


def test_needs_review_without_succeeded_attempt_can_use_original_model_regrade() -> None:
    calls: list[tuple[UUID, UUID, UUID]] = []

    class Repository:
        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> None:
            return None

        async def get_regrade_target(self, _owner_id: UUID, _item_id: UUID) -> object:
            return type(
                "RegradeTarget",
                (),
                {
                    "job_id": JOB_ID,
                    "item_status": "needs_review",
                    "has_confirmed_review": False,
                },
            )()

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            raise AssertionError("无成功 attempt 时不应读取论文正文")

    class Regrader:
        async def retry_item(self, owner_id: UUID, job_id: UUID, item_id: UUID) -> GradingJobView:
            calls.append((owner_id, job_id, item_id))
            return cast(GradingJobView, object())

    asyncio.run(
        ReviewService(
            repository=Repository(),  # type: ignore[arg-type]
            storage=Storage(),
            regrader=Regrader(),
        ).regrade(OWNER_ID, JOB_ID, ITEM_ID)
    )

    assert calls == [(OWNER_ID, JOB_ID, ITEM_ID)]


def test_concurrent_same_confirmation_returns_one_deterministic_result() -> None:
    class Repository:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.confirmed: ReviewConfirmationResult | None = None
            self.write_count = 0

        async def get_target(self, _owner_id: UUID, _item_id: UUID) -> ReviewTarget:
            return target()

        async def save_and_confirm(
            self,
            _owner_id: UUID,
            _job_id: UUID,
            _item_id: UUID,
            _data: ReviewDraftData,
        ) -> ReviewConfirmationResult:
            async with self.lock:
                if self.confirmed is None:
                    self.write_count += 1
                    self.confirmed = ReviewConfirmationResult(
                        reviews=(saved_draft(status="confirmed"),),
                        completed_job_ids=(JOB_ID,),
                    )
                return self.confirmed

    class Storage:
        async def get_json(self, _key: str) -> bytes:
            return document().model_dump_json().encode()

    repository = Repository()
    service = ReviewService(
        repository=repository,  # type: ignore[arg-type]
        storage=Storage(),
    )

    async def confirm_twice() -> tuple[ReviewConfirmationResult, ReviewConfirmationResult]:
        first, second = await asyncio.gather(
            service.confirm(OWNER_ID, JOB_ID, ITEM_ID, unchanged_payload()),
            service.confirm(OWNER_ID, JOB_ID, ITEM_ID, unchanged_payload()),
        )
        return first, second

    first, second = asyncio.run(confirm_twice())

    assert first == second
    assert repository.write_count == 1
