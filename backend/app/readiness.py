"""服务依赖就绪检查。"""

import asyncio
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


class ReadinessProbe(Protocol):
    """就绪检查接口，便于独立验证 HTTP 契约。"""

    async def database_is_available(self) -> bool:
        """返回数据库是否可用。"""
        ...


class DatabaseReadinessProbe:
    """通过一次只读查询验证数据库连接。"""

    def __init__(self, engine: AsyncEngine, timeout_seconds: float) -> None:
        self._engine = engine
        self._timeout_seconds = timeout_seconds

    async def database_is_available(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with self._engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        # 只把预期的依赖故障转为未就绪，代码错误继续向外暴露。
        except (TimeoutError, OSError, SQLAlchemyError):
            return False
        return True
