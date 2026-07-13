"""应用数据库连接池测试。"""

import asyncio
from typing import cast

from sqlalchemy.pool import QueuePool

from app.config import Settings
from app.db import Database


def test_application_database_uses_the_configured_bounded_pool() -> None:
    settings = Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        DATABASE_POOL_SIZE=3,
        DATABASE_POOL_TIMEOUT_SECONDS=4,
    )

    database = Database.from_settings(settings)
    pool = cast(QueuePool, database.engine.pool)

    assert pool.size() == 3
    assert pool.timeout() == 4
    asyncio.run(database.dispose())
