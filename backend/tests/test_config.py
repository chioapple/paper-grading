"""配置校验测试。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppEnvironment, Settings
from app.main import create_app


def clear_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除可能由开发机注入的必需配置。"""

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_required_configuration_has_no_implicit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_required_environment(monkeypatch)

    with pytest.raises(ValidationError) as error:
        Settings()

    missing_fields = {item["loc"] for item in error.value.errors() if item["type"] == "missing"}
    assert missing_fields == {("APP_ENV",), ("DATABASE_URL",)}


def test_startup_fails_without_required_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_required_environment(monkeypatch)

    with pytest.raises(ValidationError), TestClient(create_app()):
        pass


def test_explicit_test_configuration_is_valid() -> None:
    settings = Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    assert settings.app_env is AppEnvironment.TEST


def test_database_url_requires_async_postgresql_driver() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        Settings(
            APP_ENV="development",
            DATABASE_URL="sqlite+aiosqlite:///paper_grading.db",
        )


def test_malformed_database_url_is_a_configuration_error() -> None:
    with pytest.raises(ValidationError, match="格式无效"):
        Settings(APP_ENV="production", DATABASE_URL="not a database url")
