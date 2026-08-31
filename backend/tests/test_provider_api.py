"""供应商配置 HTTP 契约测试。"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_account
from app.auth.models import CurrentAccount
from app.config import Settings
from app.main import create_app
from app.providers.config import (
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderConfigView,
    ProviderTestResult,
    TeacherProviderModels,
)
from app.providers.connection import ProviderConnectionError
from app.providers.dependencies import get_provider_service
from tests.auth_settings import TEST_AUTH_SETTINGS


def build_test_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        **TEST_AUTH_SETTINGS,
    )


def test_zero_cost_runtime_does_not_construct_a_provider_connection_tester() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=build_test_settings()))
    )

    service = get_provider_service(request, object())  # type: ignore[arg-type]

    assert service._connection_tester is None


def test_admin_creates_a_provider_without_the_api_key_in_the_response() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")
    now = datetime(2026, 7, 15, tzinfo=UTC)

    class StubProviderService:
        async def create(self, payload: ProviderConfigCreate) -> ProviderConfigView:
            assert payload.api_key.get_secret_value() == "stage-five-canary-key"
            return ProviderConfigView(
                id=provider_id,
                provider_type="deepseek",
                name="DeepSeek 主账号",
                base_url="https://api.deepseek.com",
                api_key_configured=True,
                allowed_models=["deepseek-v4-flash"],
                default_model="deepseek-v4-flash",
                timeout_seconds=Decimal("60"),
                max_concurrency=2,
                monthly_budget=Decimal("20.00"),
                status="draft",
                configuration_tested=False,
                can_enable=False,
                tested_at=None,
                created_at=now,
                updated_at=now,
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.post(
            "/admin/providers",
            json={
                "provider_type": "deepseek",
                "name": "DeepSeek 主账号",
                "base_url": "https://api.deepseek.com",
                "api_key": "stage-five-canary-key",  # pragma: allowlist secret
                "allowed_models": ["deepseek-v4-flash"],
                "default_model": "deepseek-v4-flash",
                "timeout_seconds": "60",
                "max_concurrency": 2,
                "monthly_budget": "20.00",
            },
        )

    assert response.status_code == 201
    assert response.json()["api_key_configured"] is True
    assert "stage-five-canary-key" not in response.text
    assert "encrypted_api_key" not in response.text
    assert "api_key_nonce" not in response.text


def test_request_validation_error_never_echoes_an_invalid_api_key() -> None:
    invalid_api_key = "stage-five-canary-key with spaces"  # pragma: allowlist secret

    class StubProviderService:
        async def create(self, payload: ProviderConfigCreate) -> ProviderConfigView:
            raise AssertionError(f"校验失败的请求不应进入服务层：{payload!r}")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.post(
            "/admin/providers",
            json={
                "provider_type": "deepseek",
                "name": "DeepSeek 主账号",
                "base_url": "https://api.deepseek.com",
                "api_key": invalid_api_key,
                "allowed_models": ["deepseek-v4-flash"],
                "default_model": "deepseek-v4-flash",
                "timeout_seconds": "60",
                "max_concurrency": 2,
                "monthly_budget": "20.00",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "request_validation_failed",
            "message": "请求数据无效",
            "errors": [{"type": "value_error", "location": ["body", "api_key"]}],
        }
    }
    assert invalid_api_key not in response.text


def test_model_validation_error_never_echoes_the_request_body() -> None:
    api_key = "stage-five-model-validation-canary"  # pragma: allowlist secret

    class StubProviderService:
        async def create(self, payload: ProviderConfigCreate) -> ProviderConfigView:
            raise AssertionError(f"校验失败的请求不应进入服务层：{payload!r}")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.post(
            "/admin/providers",
            json={
                "provider_type": "deepseek",
                "name": "DeepSeek 主账号",
                "base_url": "https://api.deepseek.com",
                "api_key": api_key,
                "allowed_models": ["deepseek-v4-flash"],
                "default_model": "deepseek-v4-pro",
                "timeout_seconds": "60",
                "max_concurrency": 2,
                "monthly_budget": "20.00",
            },
        )

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "request_validation_failed",
            "message": "请求数据无效",
            "errors": [{"type": "value_error", "location": ["body"]}],
        }
    }
    assert api_key not in response.text
    assert "input" not in response.text
    assert "ctx" not in response.text


def test_teacher_model_catalog_only_returns_the_allowed_projection() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")

    class StubProviderService:
        async def list_teacher_models(self) -> list[TeacherProviderModels]:
            return [
                TeacherProviderModels(
                    provider_id=provider_id,
                    provider_name="DeepSeek 主账号",
                    provider_type="deepseek",
                    allowed_models=["deepseek-v4-flash"],
                    default_model="deepseek-v4-flash",
                )
            ]

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        email="teacher@example.edu",
        display_name="张老师",
        role="teacher",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.get("/providers/models")

    assert response.status_code == 200
    assert response.json() == [
        {
            "provider_id": str(provider_id),
            "provider_name": "DeepSeek 主账号",
            "provider_type": "deepseek",
            "allowed_models": ["deepseek-v4-flash"],
            "default_model": "deepseek-v4-flash",
        }
    ]
    assert "api_key" not in response.text
    assert "base_url" not in response.text


def test_admin_lists_provider_safe_views() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")
    now = datetime(2026, 7, 15, tzinfo=UTC)

    class StubProviderService:
        async def list_configs(self) -> list[ProviderConfigView]:
            return [
                ProviderConfigView(
                    id=provider_id,
                    provider_type="deepseek",
                    name="DeepSeek 主账号",
                    base_url="https://api.deepseek.com",
                    api_key_configured=True,
                    allowed_models=["deepseek-v4-flash"],
                    default_model="deepseek-v4-flash",
                    timeout_seconds=Decimal("60"),
                    max_concurrency=2,
                    monthly_budget=Decimal("20.00"),
                    status="draft",
                    configuration_tested=False,
                    can_enable=False,
                    tested_at=None,
                    created_at=now,
                    updated_at=now,
                )
            ]

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.get("/admin/providers")

    assert response.status_code == 200
    assert response.json()[0]["api_key_configured"] is True
    assert "api_key" not in response.text.replace("api_key_configured", "")


def test_admin_connection_test_returns_only_safe_results() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")
    now = datetime(2026, 7, 15, tzinfo=UTC)

    class StubProviderService:
        async def test_connection(self, requested_id: UUID) -> ProviderTestResult:
            assert requested_id == provider_id
            return ProviderTestResult(
                provider=ProviderConfigView(
                    id=provider_id,
                    provider_type="deepseek",
                    name="DeepSeek 主账号",
                    base_url="https://api.deepseek.com",
                    api_key_configured=True,
                    allowed_models=["deepseek-v4-flash"],
                    default_model="deepseek-v4-flash",
                    timeout_seconds=Decimal("60"),
                    max_concurrency=2,
                    monthly_budget=Decimal("20.00"),
                    status="draft",
                    configuration_tested=True,
                    can_enable=True,
                    tested_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                available_models=["deepseek-v4-flash", "deepseek-v4-pro"],
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.post(f"/admin/providers/{provider_id}/test")

    assert response.status_code == 200
    assert response.json()["provider"]["configuration_tested"] is True
    assert response.json()["available_models"] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert "api_key" not in response.text.replace("api_key_configured", "")


def test_wrong_provider_key_returns_a_stable_safe_http_error() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")

    class StubProviderService:
        async def test_connection(self, requested_id: UUID) -> ProviderTestResult:
            raise ProviderConnectionError(
                "provider_authentication_failed",
                "供应商 API Key 无效或无权访问",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.post(f"/admin/providers/{provider_id}/test")

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "provider_authentication_failed",
            "message": "供应商 API Key 无效或无权访问",
        }
    }


def test_admin_updates_provider_without_resending_the_api_key() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")
    now = datetime(2026, 7, 15, tzinfo=UTC)

    class StubProviderService:
        async def update(
            self,
            requested_id: UUID,
            payload: ProviderConfigUpdate,
        ) -> ProviderConfigView:
            assert requested_id == provider_id
            assert payload.api_key is None
            assert payload.default_model == "deepseek-v4-pro"
            return ProviderConfigView(
                id=provider_id,
                provider_type="deepseek",
                name="DeepSeek 主账号",
                base_url="https://api.deepseek.com",
                api_key_configured=True,
                allowed_models=["deepseek-v4-flash", "deepseek-v4-pro"],
                default_model="deepseek-v4-pro",
                timeout_seconds=Decimal("60"),
                max_concurrency=2,
                monthly_budget=Decimal("20.00"),
                status="draft",
                configuration_tested=False,
                can_enable=False,
                tested_at=None,
                created_at=now,
                updated_at=now,
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        response = client.put(
            f"/admin/providers/{provider_id}",
            json={"default_model": "deepseek-v4-pro"},
        )

    assert response.status_code == 200
    assert response.json()["default_model"] == "deepseek-v4-pro"
    assert response.json()["configuration_tested"] is False
    assert "api_key" not in response.text.replace("api_key_configured", "")


def test_admin_can_enable_and_disable_a_tested_provider() -> None:
    provider_id = UUID("33333333-3333-3333-3333-333333333333")
    now = datetime(2026, 7, 15, tzinfo=UTC)
    events: list[str] = []

    def view(status: str) -> ProviderConfigView:
        return ProviderConfigView(
            id=provider_id,
            provider_type="deepseek",
            name="DeepSeek 主账号",
            base_url="https://api.deepseek.com",
            api_key_configured=True,
            allowed_models=["deepseek-v4-flash"],
            default_model="deepseek-v4-flash",
            timeout_seconds=Decimal("60"),
            max_concurrency=2,
            monthly_budget=None,
            status=status,
            configuration_tested=True,
            can_enable=True,
            tested_at=now,
            created_at=now,
            updated_at=now,
        )

    class StubProviderService:
        async def enable(self, requested_id: UUID) -> ProviderConfigView:
            assert requested_id == provider_id
            events.append("enabled")
            return view("enabled")

        async def disable(self, requested_id: UUID) -> ProviderConfigView:
            assert requested_id == provider_id
            events.append("disabled")
            return view("disabled")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_provider_service] = StubProviderService

    with TestClient(application) as client:
        enabled_response = client.post(f"/admin/providers/{provider_id}/enable")
        disabled_response = client.post(f"/admin/providers/{provider_id}/disable")

    assert enabled_response.status_code == 200
    assert enabled_response.json()["status"] == "enabled"
    assert disabled_response.status_code == 200
    assert disabled_response.json()["status"] == "disabled"
    assert events == ["enabled", "disabled"]
