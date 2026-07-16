"""应用账户的数据库访问边界。"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import ProfileRecord
from app.db import Database
from app.domain.models import Profile


class ProfileReader(Protocol):
    """当前账户校验只需要的读取接口。"""

    async def get_by_id(self, user_id: UUID) -> ProfileRecord | None: ...


class ProfileRepository(ProfileReader, Protocol):
    """账户管理用例需要的完整持久化接口。"""

    async def get_admin(self) -> ProfileRecord | None: ...

    async def list_by_ids(self, user_ids: set[UUID]) -> list[ProfileRecord]: ...

    async def activate_invited(self, user_id: UUID) -> bool: ...

    async def disable_active(self, user_id: UUID) -> bool: ...

    async def enable_disabled(self, user_id: UUID) -> bool: ...

    async def promote_invited_to_admin(self, user_id: UUID, display_name: str) -> bool: ...


class SqlAlchemyProfileRepository:
    """基于当前事务读取 profile。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_record(profile: Profile) -> ProfileRecord:
        """在数据库边界验证角色和状态枚举。"""

        return ProfileRecord.model_validate(profile, from_attributes=True)

    async def get_by_id(self, user_id: UUID) -> ProfileRecord | None:
        profile = await self._session.get(Profile, user_id)
        if profile is None:
            return None
        return self._to_record(profile)

    async def get_admin(self) -> ProfileRecord | None:
        profile = await self._session.scalar(select(Profile).where(Profile.role == "admin"))
        if profile is None:
            return None
        return self._to_record(profile)

    async def list_by_ids(self, user_ids: set[UUID]) -> list[ProfileRecord]:
        if not user_ids:
            return []
        profiles = (
            await self._session.scalars(select(Profile).where(Profile.id.in_(user_ids)))
        ).all()
        return [self._to_record(profile) for profile in profiles]

    async def activate_invited(self, user_id: UUID) -> bool:
        result = await self._session.execute(
            update(Profile)
            .where(Profile.id == user_id, Profile.status == "invited", Profile.role == "teacher")
            .values(status="active")
            .returning(Profile.id)
        )
        await self._session.commit()
        return result.scalar_one_or_none() == user_id

    async def disable_active(self, user_id: UUID) -> bool:
        result = await self._session.execute(
            update(Profile)
            .where(Profile.id == user_id, Profile.status == "active", Profile.role == "teacher")
            .values(status="disabled")
            .returning(Profile.id)
        )
        await self._session.commit()
        return result.scalar_one_or_none() == user_id

    async def enable_disabled(self, user_id: UUID) -> bool:
        result = await self._session.execute(
            update(Profile)
            .where(Profile.id == user_id, Profile.status == "disabled", Profile.role == "teacher")
            .values(status="active")
            .returning(Profile.id)
        )
        await self._session.commit()
        return result.scalar_one_or_none() == user_id

    async def promote_invited_to_admin(self, user_id: UUID, display_name: str) -> bool:
        result = await self._session.execute(
            update(Profile)
            .where(Profile.id == user_id, Profile.status == "invited", Profile.role == "teacher")
            .values(role="admin", status="active", display_name=display_name)
            .returning(Profile.id)
        )
        await self._session.commit()
        return result.scalar_one_or_none() == user_id


class SqlAlchemyCurrentProfileReader:
    """用独立短会话读取当前 profile，避免占用后续业务连接。"""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def get_by_id(self, user_id: UUID) -> ProfileRecord | None:
        async with self._database.sessions() as session:
            return await SqlAlchemyProfileRepository(session).get_by_id(user_id)
