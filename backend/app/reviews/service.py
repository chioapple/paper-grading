"""阶段十一教师复核用例与严格评分复用。"""

from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from app.domain.grading import (
    DeductionResult,
    DimensionResult,
    EvidenceQuote,
    GradeRequest,
    GradeResult,
    canonical_json_bytes,
)
from app.grading.validator import GradeValidationError, validate_grade_response
from app.parsing.models import ParsedDocument
from app.reviews.models import (
    ReviewConfirmationRef,
    ReviewConfirmationResult,
    ReviewDetail,
    ReviewDraftData,
    ReviewDraftInput,
    ReviewDraftView,
    ReviewJobSummary,
    ReviewRegradeTarget,
    ReviewTarget,
)
from app.workers.models import GradingJobView


class ReviewRepository(Protocol):
    """复核服务当前切片使用的最小持久化边界。"""

    async def get_target(self, owner_id: UUID, item_id: UUID) -> ReviewTarget | None: ...

    async def get_regrade_target(
        self, owner_id: UUID, item_id: UUID
    ) -> ReviewRegradeTarget | None: ...

    async def list_jobs(self, owner_id: UUID) -> tuple[ReviewJobSummary, ...]: ...

    async def save_draft(
        self,
        owner_id: UUID,
        item_id: UUID,
        data: ReviewDraftData,
    ) -> ReviewDraftView: ...

    async def save_and_confirm(
        self,
        owner_id: UUID,
        job_id: UUID,
        item_id: UUID,
        data: ReviewDraftData,
    ) -> ReviewConfirmationResult: ...

    async def confirm_reviews(
        self,
        owner_id: UUID,
        job_id: UUID,
        reviews: tuple[ReviewConfirmationRef, ...],
    ) -> ReviewConfirmationResult: ...


class ReviewObjectStorage(Protocol):
    """只读取数据库已验证归属的规范文本对象。"""

    async def get_json(self, key: str) -> bytes: ...


class ReviewRegrader(Protocol):
    """阶段十原模型重评入口；固定快照和计费门禁仍由原服务负责。"""

    async def retry_item(
        self,
        owner_id: UUID,
        job_id: UUID,
        item_id: UUID,
    ) -> GradingJobView: ...


class ReviewService:
    """浏览器输入必须重新通过阶段八全部评分规则。"""

    def __init__(
        self,
        *,
        repository: ReviewRepository,
        storage: ReviewObjectStorage,
        regrader: ReviewRegrader | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._regrader = regrader

    async def list_jobs(self, owner_id: UUID) -> tuple[ReviewJobSummary, ...]:
        return await self._repository.list_jobs(owner_id)

    async def get_detail(
        self,
        owner_id: UUID,
        item_id: UUID,
        *,
        job_id: UUID | None = None,
    ) -> ReviewDetail:
        target, parsed = await self._load_target(owner_id, item_id, job_id=job_id)
        return ReviewDetail(
            job_id=target.job_id,
            item_id=target.item_id,
            item_status=target.item_status,
            assignment_id=target.assignment_id,
            assignment_title=target.assignment_title,
            assignment_instructions=target.assignment_instructions,
            rubric_version_id=target.rubric_version_id,
            rubric_version=target.rubric_version,
            rubric=target.rubric,
            submission_id=target.submission_id,
            original_filename=target.original_filename,
            document=parsed,
            attempt=target.attempt,
            draft=target.draft,
        )

    async def save_draft(
        self,
        owner_id: UUID,
        item_id: UUID,
        payload: ReviewDraftInput,
        *,
        job_id: UUID | None = None,
    ) -> ReviewDraftView:
        target, parsed = await self._load_target(owner_id, item_id, job_id=job_id)
        data = self._validate_payload(target, parsed, payload)
        return await self._repository.save_draft(owner_id, item_id, data)

    async def confirm(
        self,
        owner_id: UUID,
        job_id: UUID,
        item_id: UUID,
        payload: ReviewDraftInput,
    ) -> ReviewConfirmationResult:
        target, parsed = await self._load_target(owner_id, item_id, job_id=job_id)
        data = self._validate_payload(target, parsed, payload, require_editable=False)
        if target.item_status == "completed":
            draft = target.draft
            if draft is None or draft.status != "confirmed" or not self._matches(draft, data):
                raise ReviewConflictError("论文已经用另一复核版本确认")
        return await self._repository.save_and_confirm(owner_id, job_id, item_id, data)

    async def confirm_batch(
        self,
        owner_id: UUID,
        job_id: UUID,
        reviews: tuple[ReviewConfirmationRef, ...],
    ) -> ReviewConfirmationResult:
        if not reviews:
            raise ReviewValidationError("review_batch_empty", "批量确认不能为空")
        for reference in reviews:
            target, parsed = await self._load_target(
                owner_id,
                reference.item_id,
                job_id=job_id,
            )
            draft = target.draft
            if (
                draft is None
                or draft.id != reference.review_id
                or draft.revision_number != reference.revision_number
            ):
                raise ReviewConflictError("复核草稿版本已经变化")
            payload = ReviewDraftInput.model_validate(
                {
                    "attempt_id": draft.attempt_id,
                    "criteria": [item.model_dump(mode="json") for item in draft.criteria],
                    "deductions": [item.model_dump(mode="json") for item in draft.deductions],
                    "evidence": [item.model_dump(mode="json") for item in draft.evidence],
                    "overall_feedback": draft.overall_feedback,
                    "change_reason": draft.change_reason,
                }
            )
            validated = self._validate_payload(
                target,
                parsed,
                payload,
                require_editable=False,
            )
            if not self._matches(draft, validated):
                raise ReviewConflictError("复核草稿内容已经变化")
        return await self._repository.confirm_reviews(owner_id, job_id, reviews)

    async def regrade(
        self,
        owner_id: UUID,
        job_id: UUID,
        item_id: UUID,
    ) -> GradingJobView:
        target = await self._repository.get_regrade_target(owner_id, item_id)
        if target is None or target.job_id != job_id:
            raise ReviewNotFoundError("复核任务不存在")
        if target.item_status != "needs_review" or target.has_confirmed_review:
            raise ReviewStateError("教师确认后不能再次重评")
        if self._regrader is None:
            raise RuntimeError("复核重评服务未装配")
        return await self._regrader.retry_item(owner_id, job_id, item_id)

    async def _load_target(
        self,
        owner_id: UUID,
        item_id: UUID,
        *,
        job_id: UUID | None = None,
    ) -> tuple[ReviewTarget, ParsedDocument]:
        target = await self._repository.get_target(owner_id, item_id)
        if target is None or job_id is not None and target.job_id != job_id:
            raise ReviewNotFoundError("复核任务不存在")
        if target.item_status not in {"needs_review", "completed"}:
            raise ReviewStateError("当前论文尚不能复核")
        if target.submission_status != "ready" or target.extracted_object_key is None:
            raise ReviewDataError("review_submission_not_ready", "论文解析状态不是 ready")
        try:
            content = await self._storage.get_json(target.extracted_object_key)
            parsed = ParsedDocument.model_validate_json(content)
        except (ValidationError, ValueError) as error:
            raise ReviewDataError(
                "review_document_invalid",
                "论文规范文本对象无效",
            ) from error
        return target, parsed

    @staticmethod
    def _validate_payload(
        target: ReviewTarget,
        parsed: ParsedDocument,
        payload: ReviewDraftInput,
        *,
        require_editable: bool = True,
    ) -> ReviewDraftData:
        if require_editable and target.item_status != "needs_review":
            raise ReviewStateError("已确认复核不能修改")
        if not require_editable and target.item_status not in {"needs_review", "completed"}:
            raise ReviewStateError("当前论文不能确认")
        if payload.attempt_id != target.attempt.id:
            raise ReviewConflictError("复核草稿绑定的模型结果已经过期")

        dimension_ids = {criterion.dimension_id for criterion in payload.criteria}
        deduction_ids = {deduction.deduction_id for deduction in payload.deductions}
        grouped: dict[tuple[str, str], list[EvidenceQuote]] = {}
        for evidence in payload.evidence:
            if (
                evidence.target_type == "dimension"
                and evidence.target_id not in dimension_ids
                or evidence.target_type == "deduction"
                and evidence.target_id not in deduction_ids
            ):
                raise ReviewValidationError(
                    "review_evidence_target_unknown",
                    "教师证据引用了不存在的评分项",
                )
            grouped.setdefault((evidence.target_type, evidence.target_id), []).append(
                EvidenceQuote(block_id=evidence.block_id, quote=evidence.quote)
            )

        result = GradeResult(
            schema_version="grade-result.v1",
            dimensions=tuple(
                DimensionResult(
                    dimension_id=criterion.dimension_id,
                    score=format(criterion.score, "f"),
                    reason=criterion.reason,
                    evidence=tuple(grouped.get(("dimension", criterion.dimension_id), ())),
                    revision_suggestions=criterion.revision_suggestions,
                )
                for criterion in payload.criteria
            ),
            deductions=tuple(
                DeductionResult(
                    deduction_id=deduction.deduction_id,
                    applied=deduction.applied,
                    reason=deduction.reason,
                    evidence=tuple(grouped.get(("deduction", deduction.deduction_id), ())),
                )
                for deduction in payload.deductions
            ),
            overall_feedback=payload.overall_feedback,
        )
        request = GradeRequest(
            assignment_id=target.assignment_id,
            assignment_title=target.assignment_title,
            assignment_instructions=target.assignment_instructions,
            rubric_version_id=target.rubric_version_id,
            rubric_version=target.rubric_version,
            rubric=target.rubric,
            submission_id=target.submission_id,
            document=parsed,
        )
        try:
            validated = validate_grade_response(result, request)
        except GradeValidationError as error:
            code = error.code.removeprefix("grade_")
            raise ReviewValidationError(f"review_{code}", str(error)) from error

        original = GradeResult(
            schema_version="grade-result.v1",
            dimensions=target.attempt.dimensions,
            deductions=target.attempt.deductions,
            overall_feedback=target.attempt.overall_feedback,
        )
        changed = canonical_json_bytes(result) != canonical_json_bytes(original)
        if changed and payload.change_reason is None:
            raise ReviewValidationError(
                "review_change_reason_required",
                "修改 AI 结果时必须填写原因",
            )
        return ReviewDraftData(
            attempt_id=payload.attempt_id,
            criteria=payload.criteria,
            deductions=payload.deductions,
            evidence=payload.evidence,
            overall_feedback=payload.overall_feedback,
            change_reason=payload.change_reason,
            subtotal=validated.subtotal,
            deduction_total=validated.deduction_total,
            final_score=validated.total_score,
        )

    @staticmethod
    def _matches(draft: ReviewDraftView, data: ReviewDraftData) -> bool:
        return canonical_json_bytes(
            draft.model_dump(
                include={
                    "attempt_id",
                    "criteria",
                    "deductions",
                    "evidence",
                    "overall_feedback",
                    "change_reason",
                    "subtotal",
                    "deduction_total",
                    "final_score",
                }
            )
        ) == canonical_json_bytes(data)


class ReviewNotFoundError(LookupError):
    """跨教师和不存在资源统一表现为不可见。"""


class ReviewStateError(RuntimeError):
    """当前任务或复核状态不允许操作。"""


class ReviewConflictError(RuntimeError):
    """attempt、修订号或并发状态已经变化。"""


class ReviewValidationError(ValueError):
    """教师评分或证据违反严格评分契约。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReviewDataError(RuntimeError):
    """数据库或私有规范文本包含不能安全复核的数据。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
