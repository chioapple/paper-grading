"""安全取得阶段 11 真实教师访问令牌。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

import httpx

from app.config import Settings


async def request_access_token(
    *,
    supabase_url: str,
    publishable_key: str,
    email: str,
    password: str,
    client: httpx.AsyncClient,
) -> str:
    """通过 Supabase 密码登录取得短期 access token，不持久化凭据。"""

    try:
        response = await client.post(
            f"{supabase_url.rstrip('/')}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": publishable_key},
            json={"email": email, "password": password},
        )
    except httpx.RequestError as error:
        raise RuntimeError("无法连接 Supabase Auth") from error
    if response.status_code != 200:
        raise RuntimeError("登录失败，请检查教师邮箱、密码和账户状态")
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError("Supabase Auth 返回了无效 JSON") from error
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if (
        not isinstance(token, str)
        or len(token.split(".")) != 3
        or any(not segment for segment in token.split("."))
        or not token.isascii()
        or any(character.isspace() for character in token)
    ):
        raise RuntimeError("Supabase Auth 返回了无效访问令牌")
    return token


async def run(label: str) -> str:
    """从终端安全读取登录信息，并只向标准输出返回 access token。"""

    settings = Settings.load()
    print(f"{label}邮箱：", end="", file=sys.stderr, flush=True)
    email = input().strip()
    password = getpass.getpass(f"{label}密码（输入时不显示）：")
    if not email or not password:
        raise RuntimeError("教师邮箱和密码不能为空")
    async with httpx.AsyncClient(
        timeout=settings.supabase_auth_timeout_seconds,
        trust_env=False,
    ) as client:
        return await request_access_token(
            supabase_url=settings.supabase_url,
            publishable_key=settings.supabase_publishable_key,
            email=email,
            password=password,
            client=client,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="取得阶段 11 真实教师访问令牌")
    parser.add_argument("--label", required=True, help="提示中显示的教师名称")
    arguments = parser.parse_args()
    try:
        token = asyncio.run(run(arguments.label))
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
    print(token)


if __name__ == "__main__":
    main()
