"""阶段六作业与 Rubric 业务用例。"""

from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from app.domain.rubric import StructuredRubric
from app.providers.config import StoredProviderConfig
from app.rubrics.generation import RubricGenerationRequest, RubricGenerator
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
from app.security.encryption import ApiKeyCipher, EncryptedApiKey


class AssignmentNotFoundError(LookupError):
    """当前教师名下不存在目标作业。"""


class AssignmentStateError(RuntimeError):
    """作业状态不允许当前操作。"""


class RubricStateError(RuntimeError):
    """Rubric 版本状态不允许当前操作。"""


class RubricNotFoundError(LookupError):
    """当前作业中不存在目标 Rubric 版本。"""


class RubricProviderUnavailableError(RuntimeError):
    """所选供应商不能用于当前生成。"""


class AssignmentRubricRepository(Protocol):
    """作业与 Rubric 持久化边界。"""

    async def create_assignment(
        self,
        owner_id: UUID,
        payload: AssignmentCreate,
    ) -> AssignmentDetail: ...

    async def list_assignments(self, owner_id: UUID) -> list[AssignmentSummary]: ...

    async def get_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> AssignmentDetail | None: ...

    async def update_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: AssignmentUpdate,
    ) -> AssignmentDetail | None: ...

    async def update_assignment_status(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        action: str,
    ) -> AssignmentDetail | None: ...

    async def create_rubric_draft(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: RubricDraftCreate,
    ) -> RubricView | None: ...

    async def get_provider_for_generation(
        self,
        provider_id: UUID,
    ) -> StoredProviderConfig | None: ...

    async def save_generated_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        *,
        provider_id: UUID,
        expected_config_version: int,
        expected_model: str,
        structured_rubric: StructuredRubric,
    ) -> RubricView | None: ...

    async def update_structured_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        structured_rubric: StructuredRubric,
    ) -> RubricView | None: ...

    async def confirm_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        *,
        provider_id: UUID,
        expected_model: str,
    ) -> AssignmentDetail | None: ...


class AssignmentRubricService:
    """教师“创建作业到确认 Rubric”的单一用例入口。"""

    def __init__(
        self,
        *,
        repository: AssignmentRubricRepository,
        cipher: ApiKeyCipher | None = None,
        generator: RubricGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._generator = generator

    async def create_assignment(
        self,
        owner_id: UUID,
        payload: AssignmentCreate,
    ) -> AssignmentDetail:
        return await self._repository.create_assignment(owner_id, payload)

    async def list_assignments(self, owner_id: UUID) -> list[AssignmentSummary]:
        return await self._repository.list_assignments(owner_id)

    async def get_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> AssignmentDetail:
        assignment = await self._repository.get_assignment(owner_id, assignment_id)
        if assignment is None:
            raise AssignmentNotFoundError("作业不存在")
        return assignment

    async def update_assignment(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: AssignmentUpdate,
    ) -> AssignmentDetail:
        current = await self.get_assignment(owner_id, assignment_id)
        if current.status != "draft":
            raise AssignmentStateError("只有草稿作业可以修改")
        updated = await self._repository.update_assignment(owner_id, assignment_id, payload)
        if updated is None:
            raise AssignmentStateError("修改期间作业状态已变化")
        return updated

    async def update_assignment_status(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: AssignmentStatusUpdate,
    ) -> AssignmentDetail:
        current = await self.get_assignment(owner_id, assignment_id)
        if payload.action == "archive" and current.status == "archived":
            return current
        if payload.action == "restore" and current.status != "archived":
            raise AssignmentStateError("只有已归档作业可以恢复")
        updated = await self._repository.update_assignment_status(
            owner_id,
            assignment_id,
            payload.action,
        )
        if updated is None:
            raise AssignmentStateError("更新期间作业状态已变化")
        return updated

    async def create_rubric_draft(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        payload: RubricDraftCreate,
    ) -> RubricView:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment.status == "archived":
            raise AssignmentStateError("已归档作业不能创建 Rubric 草稿")
        if any(rubric.status == "draft" for rubric in assignment.rubric_versions):
            raise RubricStateError("作业已有 Rubric 草稿")
        draft = await self._repository.create_rubric_draft(owner_id, assignment_id, payload)
        if draft is None:
            raise RubricStateError("创建期间 Rubric 版本状态已变化")
        return draft

    async def structure_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        payload: RubricStructureRequest,
    ) -> RubricView:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment.status == "archived":
            raise AssignmentStateError("已归档作业不能生成 Rubric")
        rubric = next(
            (item for item in assignment.rubric_versions if item.id == rubric_id),
            None,
        )
        if rubric is None:
            raise RubricNotFoundError("Rubric 版本不存在")
        if rubric.status != "draft":
            raise RubricStateError("只有 Rubric 草稿可以生成结构化内容")

        provider = await self._repository.get_provider_for_generation(payload.provider_config_id)
        if (
            provider is None
            or provider.status != "enabled"
            or provider.tested_at is None
            or provider.tested_config_version != provider.config_version
            or provider.default_model is None
            or provider.encrypted_api_key is None
            or provider.api_key_nonce is None
        ):
            raise RubricProviderUnavailableError("所选供应商当前不可用于生成")
        if self._cipher is None or self._generator is None:
            raise RuntimeError("Rubric 生成能力尚未配置")

        api_key = self._cipher.decrypt(
            EncryptedApiKey(
                ciphertext=provider.encrypted_api_key,
                nonce=provider.api_key_nonce,
            ),
            provider_id=provider.id,
        )
        structured = await self._generator.generate(
            RubricGenerationRequest(
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                api_key=SecretStr(api_key),
                model=provider.default_model,
                timeout_seconds=provider.timeout_seconds,
                assignment_title=assignment.title,
                assignment_instructions=assignment.instructions,
                original_rubric=rubric.original_rubric,
                total_score=rubric.total_score,
                score_step=rubric.score_step,
            )
        )
        saved = await self._repository.save_generated_rubric(
            owner_id,
            assignment_id,
            rubric_id,
            provider_id=provider.id,
            expected_config_version=provider.config_version,
            expected_model=provider.default_model,
            structured_rubric=structured,
        )
        if saved is None:
            raise RubricStateError("生成期间供应商配置或 Rubric 状态已变化")
        return saved

    async def update_structured_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
        payload: RubricStructuredUpdate,
    ) -> RubricView:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment.status == "archived":
            raise AssignmentStateError("已归档作业不能修改 Rubric")
        rubric = next(
            (item for item in assignment.rubric_versions if item.id == rubric_id),
            None,
        )
        if rubric is None:
            raise RubricNotFoundError("Rubric 版本不存在")
        if rubric.status != "draft":
            raise RubricStateError("只有 Rubric 草稿可以修改")
        if rubric.provider_config_id is None or rubric.model is None:
            raise RubricStateError("Rubric 草稿尚未生成结构化内容")
        if (
            payload.structured_rubric.total_score != rubric.total_score
            or payload.structured_rubric.score_step != rubric.score_step
        ):
            raise RubricStateError("结构化 Rubric 的总分或评分步长不一致")
        updated = await self._repository.update_structured_rubric(
            owner_id,
            assignment_id,
            rubric_id,
            payload.structured_rubric,
        )
        if updated is None:
            raise RubricStateError("修改期间 Rubric 状态已变化")
        return updated

    async def confirm_rubric(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        rubric_id: UUID,
    ) -> AssignmentDetail:
        assignment = await self.get_assignment(owner_id, assignment_id)
        if assignment.status == "archived":
            raise AssignmentStateError("已归档作业不能确认 Rubric")
        rubric = next(
            (item for item in assignment.rubric_versions if item.id == rubric_id),
            None,
        )
        if rubric is None:
            raise RubricNotFoundError("Rubric 版本不存在")
        if rubric.status == "confirmed" and assignment.status == "ready":
            return assignment
        if rubric.status != "draft":
            raise RubricStateError("只有 Rubric 草稿可以确认")
        if (
            rubric.structured_rubric is None
            or rubric.provider_config_id is None
            or rubric.model is None
        ):
            raise RubricStateError("Rubric 草稿尚未完成结构化生成")
        confirmed = await self._repository.confirm_rubric(
            owner_id,
            assignment_id,
            rubric_id,
            provider_id=rubric.provider_config_id,
            expected_model=rubric.model,
        )
        if confirmed is None:
            raise RubricStateError("确认期间供应商配置或 Rubric 状态已变化")
        return confirmed
