"""阶段六作业与 Rubric 的 FastAPI 依赖装配。"""

from fastapi import Request

from app.db import Database
from app.providers.connection import ProviderBaseUrlPolicy
from app.rubrics.generation import HttpCoreRubricClient, OpenAICompatibleRubricGenerator
from app.rubrics.repository import SqlAlchemyAssignmentRubricRepository
from app.rubrics.service import AssignmentRubricService
from app.security.encryption import ApiKeyCipher


def get_assignment_rubric_service(request: Request) -> AssignmentRubricService:
    """每次请求使用短数据库事务，并只在外部生成期间保持 HTTP 连接。"""

    database: Database = request.app.state.database
    settings = request.app.state.settings
    generator = None
    if settings.provider_calls_enabled:
        generator = OpenAICompatibleRubricGenerator(
            url_policy=ProviderBaseUrlPolicy(
                allow_official_fake_ip=settings.allow_official_provider_fake_ip,
            ),
            http_client=HttpCoreRubricClient(),
        )
    return AssignmentRubricService(
        repository=SqlAlchemyAssignmentRubricRepository(database),
        cipher=ApiKeyCipher.from_base64_master_key(settings.provider_master_key.get_secret_value()),
        generator=generator,
        provider_calls_enabled=settings.provider_calls_enabled,
    )
