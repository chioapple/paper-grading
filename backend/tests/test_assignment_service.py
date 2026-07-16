"""阶段六作业与 Rubric 用例契约测试。"""

import base64
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.providers.config import StoredProviderConfig
from app.providers.connection import ProviderBaseUrlPolicy, ProviderHttpResponse
from app.rubrics.generation import OpenAICompatibleRubricGenerator
from app.rubrics.models import (
    AssignmentCreate,
    AssignmentDetail,
    AssignmentStatusUpdate,
    AssignmentSummary,
    AssignmentUpdate,
    RubricDraftCreate,
    RubricStructuredUpdate,
    RubricStructureRequest,
    RubricView,
)
from app.rubrics.service import (
    AssignmentRubricService,
    AssignmentStateError,
    RubricProviderUnavailableError,
    RubricStateError,
)
from app.security.encryption import ApiKeyCipher

OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")


class InMemoryAssignmentRepository:
    """只通过服务公开接口观察行为的内存数据库边界。"""

    def __init__(self) -> None:
        self.assignments: dict[UUID, AssignmentDetail] = {}
        self.providers: dict[UUID, StoredProviderConfig] = {}

    async def create_assignment(
        self,
        owner_id: UUID,
        payload: AssignmentCreate,
    ) -> AssignmentDetail:
        now = datetime(2026, 7, 16, tzinfo=UTC)
        assignment_id = uuid4()
        rubric = RubricView(
            id=uuid4(),
            assignment_id=assignment_id,
            version=1,
            status="draft",
            original_rubric=payload.original_rubric,
            structured_rubric=None,
            total_score=payload.total_score,
            score_step=payload.score_step,
            provider_config_id=None,
            model=None,
            confirmed_at=None,
            created_at=now,
        )
        detail = AssignmentDetail(
            id=assignment_id,
            title=payload.title,
            instructions=payload.instructions,
            status="draft",
            current_rubric_status="draft",
            current_rubric_version=1,
            current_draft_version=1,
            current_confirmed_version=None,
            created_at=now,
            updated_at=now,
            rubric_versions=[rubric],
        )
        self.assignments[assignment_id] = detail
        return detail

    async def list_assignments(self, owner_id: UUID) -> list[AssignmentSummary]:
        assert owner_id == OWNER_ID
        return [AssignmentSummary.model_validate(item) for item in self.assignments.values()]

    async def get_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> AssignmentDetail | None:
        assert owner_id == OWNER_ID
        return self.assignments.get(assignment_id)

    async def update_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: AssignmentUpdate,
    ) -> AssignmentDetail | None:
        current = await self.get_assignment(owner_id, assignment_id)
        if current is None or current.status != "draft":
            return None
        updated = current.model_copy(update=payload.model_dump())
        self.assignments[assignment_id] = updated
        return updated

    async def update_assignment_status(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        status: str,
    ) -> AssignmentDetail | None:
        current = await self.get_assignment(owner_id, assignment_id)
        if current is None:
            return None
        updated = current.model_copy(update={"status": status})
        self.assignments[assignment_id] = updated
        return updated

    async def create_rubric_draft(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: RubricDraftCreate,
    ) -> RubricView | None:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment is None or assignment.status == "archived":
            return None
        if any(rubric.status == "draft" for rubric in assignment.rubric_versions):
            return None
        rubric = RubricView(
            id=uuid4(),
            assignment_id=assignment_id,
            version=max(item.version for item in assignment.rubric_versions) + 1,
            status="draft",
            original_rubric=payload.original_rubric,
            structured_rubric=None,
            total_score=payload.total_score,
            score_step=payload.score_step,
            provider_config_id=None,
            model=None,
            confirmed_at=None,
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        self.assignments[assignment_id] = assignment.model_copy(
            update={
                "current_rubric_status": "draft",
                "current_rubric_version": rubric.version,
                "current_draft_version": rubric.version,
                "rubric_versions": [rubric, *assignment.rubric_versions],
            }
        )
        return rubric

    async def get_provider_for_generation(
        self,
        provider_id: UUID,
    ) -> StoredProviderConfig | None:
        return self.providers.get(provider_id)

    async def save_generated_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        *,
        provider_id: UUID,
        expected_config_version: int,
        expected_model: str,
        structured_rubric: object,
    ) -> RubricView | None:
        provider = self.providers.get(provider_id)
        assignment = await self.get_assignment(owner_id, assignment_id)
        if (
            provider is None
            or provider.status != "enabled"
            or provider.config_version != expected_config_version
            or provider.tested_config_version != provider.config_version
            or provider.default_model != expected_model
            or assignment is None
        ):
            return None
        for index, rubric in enumerate(assignment.rubric_versions):
            if rubric.id == rubric_id and rubric.status == "draft":
                updated = rubric.model_copy(
                    update={
                        "provider_config_id": provider_id,
                        "model": expected_model,
                        "structured_rubric": structured_rubric,
                    }
                )
                versions = list(assignment.rubric_versions)
                versions[index] = updated
                self.assignments[assignment_id] = assignment.model_copy(
                    update={"rubric_versions": versions}
                )
                return updated
        return None

    async def update_structured_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        structured_rubric: object,
    ) -> RubricView | None:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment is None:
            return None
        for index, rubric in enumerate(assignment.rubric_versions):
            if (
                rubric.id == rubric_id
                and rubric.status == "draft"
                and rubric.provider_config_id is not None
                and rubric.model is not None
            ):
                updated = rubric.model_copy(update={"structured_rubric": structured_rubric})
                versions = list(assignment.rubric_versions)
                versions[index] = updated
                self.assignments[assignment_id] = assignment.model_copy(
                    update={"rubric_versions": versions}
                )
                return updated
        return None

    async def confirm_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        *,
        provider_id: UUID,
        expected_model: str,
    ) -> AssignmentDetail | None:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment is None or assignment.status == "archived":
            return None
        target = next(
            (item for item in assignment.rubric_versions if item.id == rubric_id),
            None,
        )
        if (
            target is None
            or target.status != "draft"
            or target.structured_rubric is None
            or target.provider_config_id is None
            or target.model is None
        ):
            return None
        provider = self.providers.get(provider_id)
        if (
            target.provider_config_id != provider_id
            or target.model != expected_model
            or provider is None
            or provider.status != "enabled"
            or provider.tested_config_version != provider.config_version
            or provider.default_model != expected_model
        ):
            return None
        now = datetime(2026, 7, 16, tzinfo=UTC)
        versions: list[RubricView] = []
        for rubric in assignment.rubric_versions:
            if rubric.id == rubric_id:
                versions.append(
                    rubric.model_copy(update={"status": "confirmed", "confirmed_at": now})
                )
            elif rubric.status == "confirmed":
                versions.append(rubric.model_copy(update={"status": "superseded"}))
            else:
                versions.append(rubric)
        confirmed = assignment.model_copy(
            update={
                "status": "ready",
                "current_rubric_status": "confirmed",
                "current_rubric_version": target.version,
                "current_draft_version": None,
                "current_confirmed_version": target.version,
                "rubric_versions": versions,
            }
        )
        self.assignments[assignment_id] = confirmed
        return confirmed


@pytest.mark.anyio
async def test_teacher_creates_and_lists_an_assignment_with_its_first_rubric_draft() -> None:
    repository = InMemoryAssignmentRepository()
    service = AssignmentRubricService(repository=repository)

    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words with cited evidence.",
            original_rubric="Thesis 40; evidence 60.",
            total_score=Decimal("100"),
            score_step=Decimal("1"),
        ),
    )
    listed = await service.list_assignments(OWNER_ID)

    assert created.status == "draft"
    assert created.rubric_versions[0].version == 1
    assert created.rubric_versions[0].structured_rubric is None
    assert [(item.id, item.current_rubric_status) for item in listed] == [(created.id, "draft")]


@pytest.mark.anyio
async def test_teacher_can_edit_assignment_text_only_while_it_is_a_draft() -> None:
    repository = InMemoryAssignmentRepository()
    service = AssignmentRubricService(repository=repository)
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 40; evidence 60.",
            total_score="100",
            score_step="1",
        ),
    )

    updated = await service.update_assignment(
        OWNER_ID,
        created.id,
        AssignmentUpdate(
            title="Evidence-based Essay",
            instructions="Write 900 words with cited evidence.",
        ),
    )
    repository.assignments[created.id] = updated.model_copy(update={"status": "ready"})

    with pytest.raises(AssignmentStateError, match="草稿作业"):
        await service.update_assignment(
            OWNER_ID,
            created.id,
            AssignmentUpdate(title="Changed again", instructions="Not allowed."),
        )

    assert updated.title == "Evidence-based Essay"


@pytest.mark.anyio
async def test_teacher_archives_and_restores_an_assignment_without_marking_it_ready() -> None:
    repository = InMemoryAssignmentRepository()
    service = AssignmentRubricService(repository=repository)
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 40; evidence 60.",
            total_score="100",
            score_step="1",
        ),
    )

    archived = await service.update_assignment_status(
        OWNER_ID,
        created.id,
        AssignmentStatusUpdate(status="archived"),
    )
    restored = await service.update_assignment_status(
        OWNER_ID,
        created.id,
        AssignmentStatusUpdate(status="draft"),
    )

    assert archived.status == "archived"
    assert restored.status == "draft"


@pytest.mark.anyio
async def test_revision_creates_a_new_draft_without_overwriting_the_confirmed_version() -> None:
    repository = InMemoryAssignmentRepository()
    service = AssignmentRubricService(repository=repository)
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 40; evidence 60.",
            total_score="100",
            score_step="1",
        ),
    )
    confirmed = created.rubric_versions[0].model_copy(
        update={"status": "confirmed", "confirmed_at": datetime(2026, 7, 16, tzinfo=UTC)}
    )
    repository.assignments[created.id] = created.model_copy(
        update={
            "status": "ready",
            "current_rubric_status": "confirmed",
            "current_confirmed_version": 1,
            "current_draft_version": None,
            "rubric_versions": [confirmed],
        }
    )

    revision = await service.create_rubric_draft(
        OWNER_ID,
        created.id,
        RubricDraftCreate(
            original_rubric="Thesis 30; evidence 70.",
            total_score="100",
            score_step="1",
        ),
    )
    detail = await service.get_assignment(OWNER_ID, created.id)

    assert revision.version == 2
    assert detail.status == "ready"
    assert [(item.version, item.status) for item in detail.rubric_versions] == [
        (2, "draft"),
        (1, "confirmed"),
    ]
    with pytest.raises(RubricStateError, match="已有 Rubric 草稿"):
        await service.create_rubric_draft(
            OWNER_ID,
            created.id,
            RubricDraftCreate(
                original_rubric="A third version.",
                total_score="100",
                score_step="1",
            ),
        )


class PublicDeepSeekResolver:
    async def resolve(self, host: str, port: int) -> tuple[str, ...]:
        return ("8.8.8.8",)


def valid_structured_rubric_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "total_score": "100",
        "score_step": "1",
        "dimensions": [
            {
                "id": "thesis",
                "name": "Thesis",
                "description": "Quality of the central claim.",
                "max_score": "100",
                "bands": [
                    {
                        "label": "Missing",
                        "min_score": "0",
                        "max_score": "0",
                        "description": "No thesis.",
                    },
                    {
                        "label": "Present",
                        "min_score": "1",
                        "max_score": "100",
                        "description": "A defensible thesis.",
                    },
                ],
                "evidence_requirements": ["Quote the thesis statement."],
            }
        ],
        "deductions": [],
    }


class StructuredRubricHttpClient:
    async def post_json(self, **kwargs: object) -> ProviderHttpResponse:
        return ProviderHttpResponse(
            status_code=200,
            json_body={
                "id": "chatcmpl-stage-six",
                "object": "chat.completion",
                "created": 1784170800,
                "model": "deepseek-chat",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(valid_structured_rubric_payload()),
                            "reasoning_content": None,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 120,
                    "total_tokens": 200,
                },
            },
        )


def build_generation_service() -> tuple[
    InMemoryAssignmentRepository,
    AssignmentRubricService,
    UUID,
]:
    repository = InMemoryAssignmentRepository()
    cipher = ApiKeyCipher.from_base64_master_key(base64.b64encode(bytes(range(32))).decode("ascii"))
    provider_id = UUID("33333333-3333-3333-3333-333333333333")
    encrypted = cipher.encrypt("provider-secret", provider_id=provider_id)
    now = datetime(2026, 7, 16, tzinfo=UTC)
    repository.providers[provider_id] = StoredProviderConfig(
        id=provider_id,
        provider_type="deepseek",
        name="DeepSeek 主账号",
        base_url="https://api.deepseek.com",
        encrypted_api_key=encrypted.ciphertext,
        api_key_nonce=encrypted.nonce,
        allowed_models=["deepseek-chat"],
        default_model="deepseek-chat",
        timeout_seconds="60",
        max_concurrency=2,
        monthly_budget=None,
        status="enabled",
        config_version=3,
        tested_config_version=3,
        tested_at=now,
        created_at=now,
        updated_at=now,
    )
    service = AssignmentRubricService(
        repository=repository,
        cipher=cipher,
        generator=OpenAICompatibleRubricGenerator(
            url_policy=ProviderBaseUrlPolicy(resolver=PublicDeepSeekResolver()),
            http_client=StructuredRubricHttpClient(),
        ),
    )
    return repository, service, provider_id


@pytest.mark.anyio
async def test_structure_uses_the_selected_enabled_providers_current_default_model() -> None:
    repository, service, provider_id = build_generation_service()
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 100.",
            total_score="100",
            score_step="1",
        ),
    )

    structured = await service.structure_rubric(
        OWNER_ID,
        created.id,
        created.rubric_versions[0].id,
        RubricStructureRequest(provider_config_id=provider_id),
    )

    assert structured.provider_config_id == provider_id
    assert structured.model == "deepseek-chat"
    assert structured.structured_rubric is not None
    assert structured.structured_rubric.total_score == Decimal("100")


@pytest.mark.anyio
async def test_structure_rejects_a_provider_whose_current_version_is_not_tested() -> None:
    repository, service, provider_id = build_generation_service()
    provider = repository.providers[provider_id]
    repository.providers[provider_id] = provider.model_copy(
        update={"tested_config_version": provider.config_version - 1}
    )
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 100.",
            total_score="100",
            score_step="1",
        ),
    )

    with pytest.raises(RubricProviderUnavailableError, match="不可用于生成"):
        await service.structure_rubric(
            OWNER_ID,
            created.id,
            created.rubric_versions[0].id,
            RubricStructureRequest(provider_config_id=provider_id),
        )


@pytest.mark.anyio
async def test_teacher_can_replace_a_generated_drafts_structured_rubric() -> None:
    _repository, service, provider_id = build_generation_service()
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 100.",
            total_score="100",
            score_step="1",
        ),
    )
    rubric_id = created.rubric_versions[0].id
    await service.structure_rubric(
        OWNER_ID,
        created.id,
        rubric_id,
        RubricStructureRequest(provider_config_id=provider_id),
    )
    edited_payload = valid_structured_rubric_payload()
    dimensions = edited_payload["dimensions"]
    assert isinstance(dimensions, list)
    first_dimension = dimensions[0]
    assert isinstance(first_dimension, dict)
    first_dimension["description"] = "Teacher-reviewed thesis standard."

    updated = await service.update_structured_rubric(
        OWNER_ID,
        created.id,
        rubric_id,
        RubricStructuredUpdate(structured_rubric=edited_payload),
    )

    assert updated.provider_config_id == provider_id
    assert updated.model == "deepseek-chat"
    assert updated.structured_rubric is not None
    assert updated.structured_rubric.dimensions[0].description == (
        "Teacher-reviewed thesis standard."
    )


@pytest.mark.anyio
async def test_confirming_a_revision_atomically_freezes_the_new_version() -> None:
    _repository, service, provider_id = build_generation_service()
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 100.",
            total_score="100",
            score_step="1",
        ),
    )
    first = await service.structure_rubric(
        OWNER_ID,
        created.id,
        created.rubric_versions[0].id,
        RubricStructureRequest(provider_config_id=provider_id),
    )
    first_confirmation = await service.confirm_rubric(OWNER_ID, created.id, first.id)
    revision = await service.create_rubric_draft(
        OWNER_ID,
        created.id,
        RubricDraftCreate(
            original_rubric="Revised thesis standard: 100.",
            total_score="100",
            score_step="1",
        ),
    )
    revision = await service.structure_rubric(
        OWNER_ID,
        created.id,
        revision.id,
        RubricStructureRequest(provider_config_id=provider_id),
    )

    second_confirmation = await service.confirm_rubric(
        OWNER_ID,
        created.id,
        revision.id,
    )

    assert first_confirmation.status == "ready"
    assert second_confirmation.status == "ready"
    assert [(item.version, item.status) for item in second_confirmation.rubric_versions] == [
        (2, "confirmed"),
        (1, "superseded"),
    ]
    assert second_confirmation.current_confirmed_version == 2


@pytest.mark.anyio
async def test_confirmation_rechecks_that_the_generation_provider_is_still_enabled() -> None:
    repository, service, provider_id = build_generation_service()
    created = await service.create_assignment(
        OWNER_ID,
        AssignmentCreate(
            title="Argumentative Essay",
            instructions="Write 800 words.",
            original_rubric="Thesis 100.",
            total_score="100",
            score_step="1",
        ),
    )
    generated = await service.structure_rubric(
        OWNER_ID,
        created.id,
        created.rubric_versions[0].id,
        RubricStructureRequest(provider_config_id=provider_id),
    )
    repository.providers[provider_id] = repository.providers[provider_id].model_copy(
        update={"status": "disabled"}
    )

    with pytest.raises(RubricStateError, match="供应商配置"):
        await service.confirm_rubric(OWNER_ID, created.id, generated.id)
