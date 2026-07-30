"""认证与账户管理 HTTP 契约测试。"""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_account_service,
    get_auth_gateway,
    get_current_account,
    get_current_profile_reader,
)
from app.auth.models import CurrentAccount, ProfileRecord, TeacherAccount
from app.auth.service import AccountStateError
from app.auth.supabase import AuthIdentity, SupabaseAuthError, SupabaseAuthGateway
from app.config import Settings
from app.main import create_app
from tests.auth_settings import TEST_AUTH_SETTINGS


def build_test_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        REDIS_URL=TEST_AUTH_SETTINGS["REDIS_URL"],
        SUPABASE_URL=TEST_AUTH_SETTINGS["SUPABASE_URL"],
        SUPABASE_PUBLISHABLE_KEY=TEST_AUTH_SETTINGS["SUPABASE_PUBLISHABLE_KEY"],
        SUPABASE_SECRET_KEY=TEST_AUTH_SETTINGS["SUPABASE_SECRET_KEY"],
        AUTH_INVITE_REDIRECT_URL=TEST_AUTH_SETTINGS["AUTH_INVITE_REDIRECT_URL"],
        FRONTEND_ORIGIN=TEST_AUTH_SETTINGS["FRONTEND_ORIGIN"],
        PROVIDER_MASTER_KEY=TEST_AUTH_SETTINGS["PROVIDER_MASTER_KEY"],
        SUPABASE_STORAGE_BUCKET=TEST_AUTH_SETTINGS["SUPABASE_STORAGE_BUCKET"],
    )


def test_startup_creates_auth_gateway_and_allows_only_the_frontend_origin() -> None:
    application = create_app(build_test_settings())

    with TestClient(application) as client:
        response = client.options(
            "/auth/me",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        assert isinstance(application.state.auth_gateway, SupabaseAuthGateway)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


@pytest.mark.parametrize(
    ("origin", "method", "headers", "origin_is_allowed"),
    [
        ("https://attacker.example", "GET", "authorization", False),
        ("null", "GET", "authorization", False),
        ("http://127.0.0.1:5173", "DELETE", "authorization", True),
        ("http://127.0.0.1:5173", "GET", "x-unapproved-header", True),
    ],
)
def test_cors_rejects_unknown_origins_methods_and_headers(
    origin: str,
    method: str,
    headers: str,
    origin_is_allowed: bool,
) -> None:
    application = create_app(build_test_settings())

    with TestClient(application) as client:
        response = client.options(
            "/auth/me",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": headers,
            },
        )

    assert response.status_code == 400
    assert ("access-control-allow-origin" in response.headers) is origin_is_allowed


def test_me_returns_the_verified_application_profile() -> None:
    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )

    with TestClient(application) as client:
        response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": "11111111-1111-1111-1111-111111111111",
        "email": "admin@example.edu",
        "display_name": "总管理员",
        "role": "admin",
        "status": "active",
    }


def test_disabled_account_old_token_is_rejected() -> None:
    class StubGateway:
        async def verify_user_token(self, token: str) -> AuthIdentity:
            assert token == "old-session-token"
            return AuthIdentity(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                email="teacher@example.edu",
            )

    class StubProfiles:
        async def get_by_id(self, user_id: UUID) -> ProfileRecord | None:
            assert user_id == UUID("22222222-2222-2222-2222-222222222222")
            return ProfileRecord(
                id=user_id,
                display_name="张老师",
                role="teacher",
                status="disabled",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_auth_gateway] = StubGateway
    application.dependency_overrides[get_current_profile_reader] = StubProfiles

    with TestClient(application) as client:
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer old-session-token"},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "account_disabled", "message": "账户已停用"}}


def test_teacher_cannot_call_admin_user_api() -> None:
    class StubAccountService:
        async def list_teachers(self) -> list[object]:
            raise AssertionError("教师身份不应进入管理员服务")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        email="teacher@example.edu",
        display_name="张老师",
        role="teacher",
        status="active",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application) as client:
        response = client.get("/admin/users")

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "admin_required", "message": "需要管理员权限"}}


def test_invited_teacher_can_complete_invite_idempotently() -> None:
    user_id = UUID("22222222-2222-2222-2222-222222222222")

    class StubAccountService:
        async def complete_invite(self, requested_id: UUID) -> ProfileRecord:
            assert requested_id == user_id
            return ProfileRecord(
                id=user_id,
                display_name="张老师",
                role="teacher",
                status="active",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=user_id,
        email="teacher@example.edu",
        display_name="张老师",
        role="teacher",
        status="invited",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application) as client:
        response = client.post("/auth/complete-invite")

    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_admin_can_invite_a_teacher() -> None:
    class StubAccountService:
        async def invite_teacher(self, *, email: str, display_name: str) -> TeacherAccount:
            assert (email, display_name) == ("teacher@example.edu", "张老师")
            return TeacherAccount(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                email=email,
                display_name=display_name,
                status="invited",
                invited_at=None,
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application) as client:
        response = client.post(
            "/admin/users/invitations",
            json={"email": "teacher@example.edu", "display_name": "张老师"},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "invited"


def test_admin_can_disable_an_active_teacher() -> None:
    teacher_id = UUID("22222222-2222-2222-2222-222222222222")

    class StubAccountService:
        async def disable_teacher(self, requested_id: UUID) -> ProfileRecord:
            assert requested_id == teacher_id
            return ProfileRecord(
                id=teacher_id,
                display_name="张老师",
                role="teacher",
                status="disabled",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application) as client:
        response = client.post(f"/admin/users/{teacher_id}/disable")

    assert response.status_code == 204
    assert response.content == b""


def test_admin_can_enable_a_disabled_teacher() -> None:
    teacher_id = UUID("22222222-2222-2222-2222-222222222222")

    class StubAccountService:
        async def enable_teacher(self, requested_id: UUID) -> ProfileRecord:
            assert requested_id == teacher_id
            return ProfileRecord(
                id=teacher_id,
                display_name="张老师",
                role="teacher",
                status="active",
            )

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application) as client:
        response = client.post(f"/admin/users/{teacher_id}/enable")

    assert response.status_code == 204


def test_invalid_account_transition_returns_a_stable_conflict_error() -> None:
    class StubAccountService:
        async def disable_teacher(self, requested_id: UUID) -> ProfileRecord:
            raise AccountStateError("只有正常教师账户可以停用")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application) as client:
        response = client.post("/admin/users/22222222-2222-2222-2222-222222222222/disable")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "account_state_conflict", "message": "账户状态已变化"}
    }


def test_supabase_admin_failure_returns_a_stable_gateway_error() -> None:
    class StubAccountService:
        async def list_teachers(self) -> list[TeacherAccount]:
            raise SupabaseAuthError("外部服务响应不得直接返回浏览器")

    application = create_app(build_test_settings())
    application.dependency_overrides[get_current_account] = lambda: CurrentAccount(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.edu",
        display_name="总管理员",
        role="admin",
        status="active",
    )
    application.dependency_overrides[get_account_service] = StubAccountService

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/admin/users")

    assert response.status_code == 502
    assert response.json() == {
        "detail": {"code": "auth_provider_unavailable", "message": "认证服务暂时不可用"}
    }
