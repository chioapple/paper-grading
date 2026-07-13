"""配置校验测试。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import AppEnvironment, MigrationSettings, Settings, TestMigrationSettings
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


def test_remote_database_url_requires_ssl() -> None:
    with pytest.raises(ValidationError, match="ssl=require"):
        MigrationSettings(MIGRATION_DATABASE_URL="postgresql+asyncpg://db.test.supabase.co/db")


def test_production_database_rejects_transaction_pooler() -> None:
    with pytest.raises(ValidationError, match="session pooler 5432"):
        Settings(
            APP_ENV="production",
            DATABASE_URL=(
                "postgresql+asyncpg://aws-0-test.pooler.supabase.com:6543/db?ssl=require"
            ),
        )


def test_migration_configuration_requires_an_independent_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        MigrationSettings()

    assert {item["loc"] for item in error.value.errors()} == {("MIGRATION_DATABASE_URL",)}


def test_migration_url_requires_async_postgresql_driver() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        MigrationSettings(MIGRATION_DATABASE_URL="postgresql://localhost/paper_grading")


def test_remote_migration_rejects_pooler_address() -> None:
    with pytest.raises(ValidationError, match="direct"):
        MigrationSettings(
            MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://aws-0-test.pooler.supabase.com:5432/db?ssl=require"
            )
        )


def test_postgres_contract_requires_an_independent_test_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_MIGRATION_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError) as error:
        TestMigrationSettings(
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        )

    assert {item["loc"] for item in error.value.errors()} == {("TEST_MIGRATION_DATABASE_URL",)}


def test_postgres_contract_url_requires_async_postgresql_driver() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL="postgresql://localhost/paper_grading_test",
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        )


def test_postgres_contract_requires_destructive_reset_confirmation() -> None:
    with pytest.raises(ValidationError):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_SUPABASE_PROJECT_REF="test-project",
        )


def test_postgres_contract_project_ref_must_match_url() -> None:
    with pytest.raises(ValidationError, match="project ref"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_SUPABASE_PROJECT_REF="other-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        )


def test_postgres_contract_rejects_deployment_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql+asyncpg://db.same-project.supabase.co:5432/postgres?ssl=require"
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)

    with pytest.raises(ValidationError, match="部署迁移库"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=database_url,
            TEST_SUPABASE_PROJECT_REF="same-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        )
