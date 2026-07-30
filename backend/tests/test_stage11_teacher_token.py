"""阶段 11 教师令牌辅助脚本测试。"""

import httpx
import pytest

from scripts.stage11_teacher_token import request_access_token


@pytest.mark.anyio
async def test_requests_password_session_without_printing_or_persisting_secrets() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == ("https://test-project.supabase.co/auth/v1/token?grant_type=password")
        assert request.headers["apikey"] == "sb_publishable_test"  # pragma: allowlist secret
        expected_body = (
            b'{"email":"teacher@example.edu","password":"secret"}'  # pragma: allowlist secret
        )
        assert request.read() == expected_body
        return httpx.Response(200, json={"access_token": "header.payload.signature"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await request_access_token(
            supabase_url="https://test-project.supabase.co",
            publishable_key="sb_publishable_test",
            email="teacher@example.edu",
            password="secret",  # pragma: allowlist secret
            client=client,
        )

    assert token == "header.payload.signature"


@pytest.mark.anyio
async def test_rejects_invalid_auth_response_without_exposing_remote_details() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error_description": "remote secret detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="登录失败") as caught:
            await request_access_token(
                supabase_url="https://test-project.supabase.co",
                publishable_key="sb_publishable_test",
                email="teacher@example.edu",
                password="wrong",  # pragma: allowlist secret
                client=client,
            )

    assert "remote secret detail" not in str(caught.value)
