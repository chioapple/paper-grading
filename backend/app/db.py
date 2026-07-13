"""应用数据库连接池与会话入口。"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


@dataclass(frozen=True, slots=True)
class Database:
    """集中持有应用连接池和会话工厂。"""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        """使用有界连接池创建数据库入口。"""

        engine = create_async_engine(
            settings.database_url,
            pool_size=settings.database_pool_size,
            max_overflow=0,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_pre_ping=True,
        )
        return cls(
            engine=engine,
            sessions=async_sessionmaker(engine, expire_on_commit=False),
        )

    async def dispose(self) -> None:
        """关闭连接池。"""

        await self.engine.dispose()
