"""数据库就绪探针测试。"""

import asyncio
from typing import cast

from sqlalchemy.ext.asyncio import AsyncEngine

from app.readiness import DatabaseReadinessProbe


class FakeConnection:
    """记录探针执行的 SQL。"""

    def __init__(self) -> None:
        self.executed_sql: str | None = None

    async def __aenter__(self) -> "FakeConnection":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> None:
        self.executed_sql = str(statement)


class AvailableEngine:
    """返回可用连接。"""

    def __init__(self) -> None:
        self.connection = FakeConnection()

    def connect(self) -> FakeConnection:
        return self.connection


class UnavailableEngine:
    """模拟连接初始化失败。"""

    def connect(self) -> FakeConnection:
        raise OSError("database unavailable")


def test_database_probe_runs_read_only_query() -> None:
    engine = AvailableEngine()
    probe = DatabaseReadinessProbe(
        engine=cast(AsyncEngine, engine),
        timeout_seconds=1,
    )

    result = asyncio.run(probe.database_is_available())

    assert result is True
    assert engine.connection.executed_sql == "SELECT 1"


def test_database_probe_reports_connection_failure() -> None:
    probe = DatabaseReadinessProbe(
        engine=cast(AsyncEngine, UnavailableEngine()),
        timeout_seconds=1,
    )

    result = asyncio.run(probe.database_is_available())

    assert result is False
