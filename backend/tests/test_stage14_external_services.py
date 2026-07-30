"""阶段 14 独立外部服务门禁；普通 pytest 明确排除。"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import pytest
import redis
from celery import Celery

pytestmark = pytest.mark.external


def required_environment(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"缺少阶段 14 外部验收变量：{name}", pytrace=False)
    return value


def supabase_headers(key: str, *, token: str | None = None) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {token or key}",
    }


def test_real_supabase_auth_and_jwt() -> None:
    base_url = required_environment("STAGE14_TEST_SUPABASE_URL").rstrip("/")
    publishable_key = required_environment("STAGE14_TEST_SUPABASE_PUBLISHABLE_KEY")
    email = required_environment("STAGE14_TEST_TEACHER_EMAIL")
    password = required_environment("STAGE14_TEST_TEACHER_PASSWORD")

    with httpx.Client(timeout=20, trust_env=False) as client:
        login = client.post(
            f"{base_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers=supabase_headers(publishable_key),
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, "独立测试项目登录失败"
        payload = login.json()
        token = payload.get("access_token")
        assert isinstance(token, str) and token, "登录响应缺少 access token"

        verified = client.get(
            f"{base_url}/auth/v1/user",
            headers=supabase_headers(publishable_key, token=token),
        )
        assert verified.status_code == 200, "JWT 无法在同一测试项目验证"
        assert verified.json().get("email") == email

        tampered_token = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
        rejected = client.get(
            f"{base_url}/auth/v1/user",
            headers=supabase_headers(publishable_key, token=tampered_token),
        )
        assert rejected.status_code in {401, 403}, "篡改 JWT 未被拒绝"

        logout = client.post(
            f"{base_url}/auth/v1/logout",
            headers=supabase_headers(publishable_key, token=token),
        )
        assert logout.status_code in {200, 204}, "测试会话注销失败"


def test_real_account_deactivation_and_admin_boundary() -> None:
    if (
        os.environ.get("STAGE14_ALLOW_ACCOUNT_STATE_WRITES")
        != "I_ACCEPT_DISABLE_AND_REENABLE_TEST_TEACHER"
    ):
        pytest.fail("缺少测试教师停用与恢复授权", pytrace=False)
    supabase_url = required_environment("STAGE14_TEST_SUPABASE_URL").rstrip("/")
    publishable_key = required_environment("STAGE14_TEST_SUPABASE_PUBLISHABLE_KEY")
    api_base_url = required_environment("STAGE14_TEST_API_BASE_URL").rstrip("/")
    admin_email = required_environment("STAGE14_TEST_ADMIN_EMAIL")
    admin_password = required_environment("STAGE14_TEST_ADMIN_PASSWORD")
    teacher_email = required_environment("STAGE14_TEST_TEACHER_EMAIL")
    teacher_password = required_environment("STAGE14_TEST_TEACHER_PASSWORD")

    with httpx.Client(timeout=30, trust_env=False) as client:

        def login(email: str, password: str) -> tuple[str, str]:
            response = client.post(
                f"{supabase_url}/auth/v1/token",
                params={"grant_type": "password"},
                headers=supabase_headers(publishable_key),
                json={"email": email, "password": password},
            )
            assert response.status_code == 200, "独立测试项目账户登录失败"
            payload = response.json()
            token = payload.get("access_token")
            user_id = payload.get("user", {}).get("id")
            assert isinstance(token, str) and token
            assert isinstance(user_id, str) and user_id
            return token, user_id

        admin_token, admin_id = login(admin_email, admin_password)
        teacher_token, teacher_id = login(teacher_email, teacher_password)
        assert teacher_id != admin_id, "管理员与测试教师必须是不同账户"
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

        teacher_admin_access = client.get(
            f"{api_base_url}/admin/users",
            headers=teacher_headers,
        )
        assert teacher_admin_access.status_code == 403
        assert teacher_admin_access.json().get("detail", {}).get("code") == "admin_required"

        directory = client.get(f"{api_base_url}/admin/users", headers=admin_headers)
        assert directory.status_code == 200
        matching = [item for item in directory.json() if item.get("id") == teacher_id]
        assert len(matching) == 1
        assert matching[0].get("status") == "active", "测试教师必须从 active 状态开始"

        try:
            disabled = client.post(
                f"{api_base_url}/admin/users/{teacher_id}/disable",
                headers=admin_headers,
            )
            assert disabled.status_code == 204, "管理员停用测试教师失败"

            old_session = client.get(f"{api_base_url}/auth/me", headers=teacher_headers)
            assert old_session.status_code == 403
            assert old_session.json().get("detail", {}).get("code") == "account_disabled"

            banned_login = client.post(
                f"{supabase_url}/auth/v1/token",
                params={"grant_type": "password"},
                headers=supabase_headers(publishable_key),
                json={"email": teacher_email, "password": teacher_password},
            )
            assert banned_login.status_code in {400, 403}, "停用教师仍可重新登录"
        finally:
            restored = client.post(
                f"{api_base_url}/admin/users/{teacher_id}/enable",
                headers=admin_headers,
            )
            assert restored.status_code == 204, "测试教师恢复失败，必须人工检查测试项目"

        login(teacher_email, teacher_password)


def test_real_enabled_provider_connections() -> None:
    if os.environ.get("STAGE14_ALLOW_PROVIDER_TEST_WRITES") != "I_ACCEPT_TESTED_AT_WRITES":
        pytest.fail("缺少供应商 tested_at 写入授权", pytrace=False)
    if (
        os.environ.get("STAGE14_ALLOW_PROVIDER_CONNECTION_COSTS")
        != "I_ACCEPT_PROVIDER_CONNECTION_CALLS"
    ):
        pytest.fail("缺少供应商连接测试潜在费用授权", pytrace=False)
    supabase_url = required_environment("STAGE14_TEST_SUPABASE_URL").rstrip("/")
    publishable_key = required_environment("STAGE14_TEST_SUPABASE_PUBLISHABLE_KEY")
    api_base_url = required_environment("STAGE14_TEST_API_BASE_URL").rstrip("/")
    admin_email = required_environment("STAGE14_TEST_ADMIN_EMAIL")
    admin_password = required_environment("STAGE14_TEST_ADMIN_PASSWORD")

    with httpx.Client(timeout=30, trust_env=False) as client:
        login = client.post(
            f"{supabase_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers=supabase_headers(publishable_key),
            json={"email": admin_email, "password": admin_password},
        )
        assert login.status_code == 200, "独立测试项目管理员登录失败"
        token = login.json().get("access_token")
        assert isinstance(token, str) and token
        authorization = {"Authorization": f"Bearer {token}"}

        response = client.get(f"{api_base_url}/admin/providers", headers=authorization)
        assert response.status_code == 200, "无法读取独立测试项目供应商目录"
        enabled = [provider for provider in response.json() if provider.get("status") == "enabled"]
        assert enabled, "独立测试项目至少需要一个已启用供应商"
        for provider in enabled:
            provider_id = provider.get("id")
            assert isinstance(provider_id, str) and provider_id
            tested = client.post(
                f"{api_base_url}/admin/providers/{provider_id}/test",
                headers=authorization,
            )
            assert tested.status_code == 200, "已启用供应商无计费连接测试失败"
            payload = tested.json()
            assert payload.get("provider", {}).get("id") == provider_id
            assert payload.get("available_models"), "供应商没有返回可用模型"


def test_real_private_storage_signed_url_is_bound_to_one_object() -> None:
    base_url = required_environment("STAGE14_TEST_SUPABASE_URL").rstrip("/")
    storage_url = f"{base_url}/storage/v1"
    secret_key = required_environment("STAGE14_TEST_SUPABASE_SECRET_KEY")
    bucket = required_environment("STAGE14_TEST_STORAGE_BUCKET")
    object_key = f"stage14-acceptance/{uuid4()}.txt"
    other_key = f"stage14-acceptance/{uuid4()}.txt"
    denied_key = f"stage14-acceptance/{uuid4()}.txt"
    headers = supabase_headers(secret_key)
    publishable_key = required_environment("STAGE14_TEST_SUPABASE_PUBLISHABLE_KEY")
    teacher_email = required_environment("STAGE14_TEST_TEACHER_EMAIL")
    teacher_password = required_environment("STAGE14_TEST_TEACHER_PASSWORD")

    with httpx.Client(timeout=30, trust_env=False) as client:
        login = client.post(
            f"{base_url}/auth/v1/token",
            params={"grant_type": "password"},
            headers=supabase_headers(publishable_key),
            json={"email": teacher_email, "password": teacher_password},
        )
        assert login.status_code == 200, "独立测试项目教师登录失败"
        teacher_token = login.json().get("access_token")
        assert isinstance(teacher_token, str) and teacher_token
        teacher_headers = supabase_headers(publishable_key, token=teacher_token)

        upload = client.post(
            f"{base_url}/storage/v1/object/{bucket}/{object_key}",
            headers={**headers, "Content-Type": "text/plain"},
            content=b"stage14 external storage fixture",
        )
        assert upload.status_code in {200, 201}, "独立测试桶上传失败"
        try:
            signed = client.post(
                f"{base_url}/storage/v1/object/sign/{bucket}/{object_key}",
                headers={**headers, "Content-Type": "application/json"},
                json={"expiresIn": 60},
            )
            assert signed.status_code == 200, "签名 URL 创建失败"
            signed_path = signed.json().get("signedURL")
            assert isinstance(signed_path, str) and signed_path.startswith("/")

            download = client.get(f"{storage_url}{signed_path}")
            assert download.status_code == 200
            assert download.content == b"stage14 external storage fixture"

            unsigned = client.get(f"{base_url}/storage/v1/object/{bucket}/{object_key}")
            assert unsigned.status_code in {400, 401, 403}, "私有对象无需签名即可下载"
            teacher_download = client.get(
                f"{base_url}/storage/v1/object/{bucket}/{object_key}",
                headers=teacher_headers,
            )
            assert teacher_download.status_code in {400, 401, 403, 404}
            teacher_upload = client.post(
                f"{base_url}/storage/v1/object/{bucket}/{denied_key}",
                headers={**teacher_headers, "Content-Type": "text/plain"},
                content=b"must be rejected",
            )
            assert teacher_upload.status_code in {400, 401, 403}, (
                "教师 JWT 不得绕过 FastAPI 直接写私有桶"
            )

            tampered_path = signed_path.replace(object_key, other_key, 1)
            tampered = client.get(f"{storage_url}{tampered_path}")
            assert tampered.status_code in {400, 401, 403, 404}

            expiring = client.post(
                f"{base_url}/storage/v1/object/sign/{bucket}/{object_key}",
                headers={**headers, "Content-Type": "application/json"},
                json={"expiresIn": 1},
            )
            assert expiring.status_code == 200
            expiring_path = expiring.json().get("signedURL")
            assert isinstance(expiring_path, str) and expiring_path.startswith("/")
            time.sleep(3)
            expired = client.get(f"{storage_url}{expiring_path}")
            assert expired.status_code in {400, 401, 403}, "签名 URL 过期后仍可读取"
        finally:
            deleted = client.request(
                "DELETE",
                f"{base_url}/storage/v1/object/{bucket}",
                headers={**headers, "Content-Type": "application/json"},
                json={"prefixes": [object_key, denied_key]},
            )
            assert deleted.status_code in {200, 204}, "验收夹具清理失败"


def test_real_redis_and_three_celery_worker_heartbeats() -> None:
    redis_url = required_environment("STAGE14_TEST_REDIS_URL")
    connection = redis.Redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
    try:
        assert connection.ping() is True
    finally:
        connection.close()

    celery_app = Celery("stage14_acceptance", broker=redis_url)
    replies = celery_app.control.inspect(timeout=10).ping() or {}
    worker_names = set(replies)
    assert any(name.startswith("grading@") for name in worker_names)
    assert any(name.startswith("maintenance@") for name in worker_names)
    assert any(name.startswith("exports@") for name in worker_names)
