"""Supabase Auth 外部边界契约测试。"""

import json
from uuid import UUID

import httpx
import pytest

from app.auth.supabase import SupabaseAuthError, SupabaseAuthGateway


@pytest.mark.anyio
async def test_verify_user_token_uses_publishable_key_and_returns_identity() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://test-project.supabase.co/auth/v1/user"
        assert request.headers["apikey"] == "sb_publishable_test"  # pragma: allowlist secret
        assert request.headers["authorization"] == "Bearer teacher-token"
        return httpx.Response(
            200,
            json={
                "id": "11111111-1111-1111-1111-111111111111",
                "email": "teacher@example.edu",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        identity = await gateway.verify_user_token("teacher-token")

    assert identity.id == UUID("11111111-1111-1111-1111-111111111111")
    assert identity.email == "teacher@example.edu"


@pytest.mark.anyio
async def test_verify_user_token_rejects_non_ascii_placeholder_as_stable_auth_error() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("无效令牌不得发往 Supabase Auth")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        with pytest.raises(SupabaseAuthError, match="访问令牌无效"):
            await gateway.verify_user_token("教师A的访问令牌")


@pytest.mark.anyio
async def test_invite_teacher_uses_secret_key_only_on_server() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == (
            "https://test-project.supabase.co/auth/v1/invite"
            "?redirect_to=http%3A%2F%2F127.0.0.1%3A5173%2Fauth%2Fcallback"
        )
        assert request.headers["apikey"] == "sb_secret_test"  # pragma: allowlist secret
        assert request.headers["authorization"] == "Bearer sb_secret_test"
        assert json.loads(request.content) == {
            "email": "teacher@example.edu",
            "data": {"display_name": "张老师"},
        }
        return httpx.Response(
            200,
            json={
                "id": "22222222-2222-2222-2222-222222222222",
                "email": "teacher@example.edu",
                "invited_at": "2026-07-13T12:00:00Z",
                "created_at": "2026-07-13T12:00:00Z",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        user = await gateway.invite_teacher(
            email="teacher@example.edu",
            display_name="张老师",
        )

    assert user.id == UUID("22222222-2222-2222-2222-222222222222")
    assert user.email == "teacher@example.edu"


@pytest.mark.anyio
async def test_disable_teacher_bans_the_auth_user() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url == (
            "https://test-project.supabase.co/auth/v1/admin/users/"
            "22222222-2222-2222-2222-222222222222"
        )
        assert json.loads(request.content) == {"ban_duration": "876000h"}
        return httpx.Response(
            200,
            json={
                "id": "22222222-2222-2222-2222-222222222222",
                "email": "teacher@example.edu",
                "created_at": "2026-07-13T12:00:00Z",
                "banned_until": "2126-07-13T12:00:00Z",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        user = await gateway.disable_user(UUID("22222222-2222-2222-2222-222222222222"))

    assert user.banned_until is not None


@pytest.mark.anyio
async def test_enable_teacher_removes_the_auth_ban() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"ban_duration": "none"}
        return httpx.Response(
            200,
            json={
                "id": "22222222-2222-2222-2222-222222222222",
                "email": "teacher@example.edu",
                "created_at": "2026-07-13T12:00:00Z",
                "last_sign_in_at": "2026-07-13T13:00:00Z",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        user = await gateway.enable_user(UUID("22222222-2222-2222-2222-222222222222"))

    assert user.banned_until is None


@pytest.mark.anyio
async def test_list_users_reads_the_admin_user_page() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == (
            "https://test-project.supabase.co/auth/v1/admin/users?page=1&per_page=1000"
        )
        return httpx.Response(
            200,
            json={
                "users": [
                    {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "email": "teacher@example.edu",
                        "created_at": "2026-07-13T12:00:00Z",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        users = await gateway.list_users(page=1, per_page=1000)

    assert [user.email for user in users] == ["teacher@example.edu"]


@pytest.mark.anyio
async def test_network_failures_are_exposed_as_a_stable_auth_gateway_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network details must stay internal", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        with pytest.raises(SupabaseAuthError, match="无法连接"):
            await gateway.list_users(page=1, per_page=1000)


@pytest.mark.anyio
async def test_public_signup_must_be_disabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://test-project.supabase.co/auth/v1/settings"
        assert request.headers["apikey"] == "sb_publishable_test"  # pragma: allowlist secret
        return httpx.Response(200, json={"disable_signup": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = SupabaseAuthGateway(
            base_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            secret_key="sb_secret_test",  # pragma: allowlist secret
            invite_redirect_url="http://127.0.0.1:5173/auth/callback",
            client=client,
        )

        with pytest.raises(SupabaseAuthError, match="公开注册必须关闭"):
            await gateway.require_public_signup_disabled()
