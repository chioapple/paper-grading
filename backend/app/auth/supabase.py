"""Supabase Auth 与 Admin API 的服务端边界。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import httpx


@dataclass(frozen=True, slots=True)
class AuthIdentity:
    """Supabase 已验证的当前用户身份。"""

    id: UUID
    email: str


@dataclass(frozen=True, slots=True)
class AuthUser:
    """管理员接口返回的认证账户。"""

    id: UUID
    email: str
    invited_at: datetime | None
    created_at: datetime
    last_sign_in_at: datetime | None
    banned_until: datetime | None


class SupabaseAuthError(RuntimeError):
    """Supabase Auth 返回无效响应或拒绝请求。"""


class SupabaseAuthGateway:
    """集中封装浏览器不可访问的 Supabase Auth 调用。"""

    def __init__(
        self,
        *,
        base_url: str,
        publishable_key: str,
        secret_key: str,
        invite_redirect_url: str,
        client: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._publishable_key = publishable_key
        self._secret_key = secret_key
        self._invite_redirect_url = invite_redirect_url
        self._client = client

    async def verify_user_token(self, token: str) -> AuthIdentity:
        """让 Supabase Auth 验证访问令牌并返回可信身份。"""

        response = await self._request(
            "GET",
            f"{self._base_url}/auth/v1/user",
            headers={
                "apikey": self._publishable_key,
                "Authorization": f"Bearer {token}",
            },
        )
        if response.status_code != 200:
            raise SupabaseAuthError("访问令牌无效或已失效")
        payload = self._response_json(response)
        if not isinstance(payload, dict):
            raise SupabaseAuthError("Supabase Auth 返回了无效用户数据")
        try:
            user_id = payload["id"]
            email = payload["email"]
            if not isinstance(user_id, str) or not isinstance(email, str):
                raise ValueError("id or email")
            return AuthIdentity(id=UUID(user_id), email=email)
        except (KeyError, TypeError, ValueError) as error:
            raise SupabaseAuthError("Supabase Auth 返回了无效用户数据") from error

    async def require_public_signup_disabled(self) -> None:
        """生产启动前确认 Supabase Auth 只允许管理员邀请。"""

        response = await self._request(
            "GET",
            f"{self._base_url}/auth/v1/settings",
            headers={"apikey": self._publishable_key},
        )
        if response.status_code != 200:
            raise SupabaseAuthError("无法读取 Supabase Auth 公开设置")
        payload = self._response_json(response)
        if not isinstance(payload, dict) or payload.get("disable_signup") is not True:
            raise SupabaseAuthError("Supabase Auth 公开注册必须关闭")

    async def invite_teacher(self, *, email: str, display_name: str) -> AuthUser:
        """使用服务端密钥发送教师邀请。"""

        response = await self._request(
            "POST",
            f"{self._base_url}/auth/v1/invite",
            params={"redirect_to": self._invite_redirect_url},
            headers=self._admin_headers(),
            json={"email": email, "data": {"display_name": display_name}},
        )
        if response.status_code != 200:
            raise SupabaseAuthError("Supabase Auth 拒绝了教师邀请")
        return self._parse_auth_user(self._response_json(response))

    async def disable_user(self, user_id: UUID) -> AuthUser:
        """长期封禁认证账户，停止密码登录和会话续期。"""

        return await self._update_user(user_id, {"ban_duration": "876000h"})

    async def enable_user(self, user_id: UUID) -> AuthUser:
        """解除认证账户封禁。"""

        return await self._update_user(user_id, {"ban_duration": "none"})

    async def list_users(self, *, page: int, per_page: int) -> list[AuthUser]:
        """读取一页认证账户。"""

        response = await self._request(
            "GET",
            f"{self._base_url}/auth/v1/admin/users",
            params={"page": page, "per_page": per_page},
            headers=self._admin_headers(),
        )
        if response.status_code != 200:
            raise SupabaseAuthError("Supabase Auth 拒绝了账户列表请求")
        payload = self._response_json(response)
        if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
            raise SupabaseAuthError("Supabase Auth 返回了无效账户列表")
        return [self._parse_auth_user(item) for item in payload["users"]]

    async def _update_user(self, user_id: UUID, payload: dict[str, str]) -> AuthUser:
        response = await self._request(
            "PUT",
            f"{self._base_url}/auth/v1/admin/users/{user_id}",
            headers=self._admin_headers(),
            json=payload,
        )
        if response.status_code != 200:
            raise SupabaseAuthError("Supabase Auth 拒绝了账户状态修改")
        return self._parse_auth_user(self._response_json(response))

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        try:
            if json is None:
                return await self._client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                )
            return await self._client.request(
                method,
                url,
                params=params,
                headers=headers,
                json=json,
            )
        except httpx.RequestError as error:
            raise SupabaseAuthError("无法连接 Supabase Auth") from error

    @staticmethod
    def _response_json(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError as error:
            raise SupabaseAuthError("Supabase Auth 返回了无效 JSON") from error

    def _admin_headers(self) -> dict[str, str]:
        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
        }

    @staticmethod
    def _parse_auth_user(payload: object) -> AuthUser:
        if not isinstance(payload, dict):
            raise SupabaseAuthError("Supabase Auth 返回了无效账户数据")

        def optional_datetime(field: str) -> datetime | None:
            value = payload.get(field)
            if value is None:
                return None
            if not isinstance(value, str):
                raise ValueError(field)
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        try:
            user_id = payload["id"]
            email = payload["email"]
            created_at = payload["created_at"]
            if not isinstance(user_id, str) or not isinstance(email, str):
                raise ValueError("id or email")
            if not isinstance(created_at, str):
                raise ValueError("created_at")
            return AuthUser(
                id=UUID(user_id),
                email=email,
                invited_at=optional_datetime("invited_at"),
                created_at=datetime.fromisoformat(created_at.replace("Z", "+00:00")),
                last_sign_in_at=optional_datetime("last_sign_in_at"),
                banned_until=optional_datetime("banned_until"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SupabaseAuthError("Supabase Auth 返回了无效账户数据") from error
