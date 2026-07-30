"""一次性引导唯一总管理员。"""

import argparse
import asyncio

import httpx

from app.auth.repository import SqlAlchemyProfileRepository
from app.auth.service import AccountService
from app.auth.supabase import SupabaseAuthGateway
from app.config import Settings
from app.db import Database

BOOTSTRAP_CONFIRMATION = "I_UNDERSTAND_THIS_INVITES_AND_PROMOTES_ONE_ADMIN"


async def bootstrap_admin(*, settings: Settings, email: str, display_name: str) -> None:
    """使用显式环境配置执行一次管理员提升。"""

    database = Database.from_settings(settings)
    try:
        async with httpx.AsyncClient(
            timeout=settings.supabase_auth_timeout_seconds,
            trust_env=False,
        ) as client:
            gateway = SupabaseAuthGateway(
                base_url=settings.supabase_url,
                publishable_key=settings.supabase_publishable_key,
                secret_key=settings.supabase_secret_key.get_secret_value(),
                invite_redirect_url=settings.auth_invite_redirect_url,
                client=client,
            )
            async with database.sessions() as session:
                service = AccountService(
                    gateway=gateway,
                    profiles=SqlAlchemyProfileRepository(session),
                )
                account = await service.bootstrap_admin(
                    email=email,
                    display_name=display_name,
                )
    finally:
        await database.dispose()

    print(f"已引导总管理员：{account.email}")


def main() -> None:
    """只接受明确确认值，防止误改账户角色。"""

    parser = argparse.ArgumentParser(description="引导 Paper Grading 唯一总管理员")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--confirm", required=True)
    arguments = parser.parse_args()
    if arguments.confirm != BOOTSTRAP_CONFIRMATION:
        parser.error(f"--confirm 必须等于 {BOOTSTRAP_CONFIRMATION}")
    if not arguments.display_name.strip():
        parser.error("--display-name 不能为空")

    asyncio.run(
        bootstrap_admin(
            settings=Settings.load(),
            email=arguments.email,
            display_name=arguments.display_name,
        )
    )


if __name__ == "__main__":
    main()
