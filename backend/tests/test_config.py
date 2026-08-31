"""配置校验测试。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.config import (
    AppEnvironment,
    ExportWorkerSettings,
    MigrationSettings,
    Settings,
    TestMigrationSettings,
    WorkerSettings,
)
from app.main import create_app
from tests.auth_settings import TEST_AUTH_SETTINGS

TEST_RUNTIME_DATABASE_URL = (
    "postgresql+asyncpg://postgres.test-project:secret@"  # pragma: allowlist secret
    "aws-0-test.pooler.supabase.com:5432/postgres?ssl=require"
)


def clear_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除可能由开发机注入的必需配置。"""

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("AUTH_INVITE_REDIRECT_URL", raising=False)
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("PROVIDER_MASTER_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_STORAGE_BUCKET", raising=False)


def test_required_configuration_has_no_implicit_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_required_environment(monkeypatch)

    with pytest.raises(ValidationError) as error:
        Settings()

    missing_fields = {item["loc"] for item in error.value.errors() if item["type"] == "missing"}
    assert missing_fields == {
        ("APP_ENV",),
        ("DATABASE_URL",),
        ("REDIS_URL",),
        ("SUPABASE_URL",),
        ("SUPABASE_PUBLISHABLE_KEY",),
        ("SUPABASE_SECRET_KEY",),
        ("AUTH_INVITE_REDIRECT_URL",),
        ("FRONTEND_ORIGIN",),
        ("PROVIDER_MASTER_KEY",),
        ("SUPABASE_STORAGE_BUCKET",),
    }


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
        **TEST_AUTH_SETTINGS,
    )

    assert settings.app_env is AppEnvironment.TEST
    assert settings.provider_calls_enabled is False


def test_development_can_explicitly_allow_official_provider_vpn_fake_ip() -> None:
    settings = Settings(
        APP_ENV="development",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        ALLOW_OFFICIAL_PROVIDER_FAKE_IP=True,
        **TEST_AUTH_SETTINGS,
    )

    assert settings.allow_official_provider_fake_ip is True


def test_storage_endpoint_is_derived_from_validated_supabase_project() -> None:
    settings = Settings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        **TEST_AUTH_SETTINGS,
    )

    assert settings.supabase_storage_url == "https://test-project.supabase.co/storage/v1"


def test_provider_master_key_must_be_base64_encoded_32_bytes() -> None:
    invalid_settings = TEST_AUTH_SETTINGS.copy()
    invalid_settings["PROVIDER_MASTER_KEY"] = "not-a-master-key"
    with pytest.raises(ValidationError, match="32 字节"):
        Settings(
            APP_ENV="test",
            DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
            **invalid_settings,
        )


def test_settings_loads_required_values_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    monkeypatch.setenv("REDIS_URL", TEST_AUTH_SETTINGS["REDIS_URL"])
    monkeypatch.setenv("SUPABASE_URL", TEST_AUTH_SETTINGS["SUPABASE_URL"])
    monkeypatch.setenv(
        "SUPABASE_PUBLISHABLE_KEY",
        TEST_AUTH_SETTINGS["SUPABASE_PUBLISHABLE_KEY"],
    )
    monkeypatch.setenv("SUPABASE_SECRET_KEY", TEST_AUTH_SETTINGS["SUPABASE_SECRET_KEY"])
    monkeypatch.setenv(
        "AUTH_INVITE_REDIRECT_URL",
        TEST_AUTH_SETTINGS["AUTH_INVITE_REDIRECT_URL"],
    )
    monkeypatch.setenv("FRONTEND_ORIGIN", TEST_AUTH_SETTINGS["FRONTEND_ORIGIN"])
    monkeypatch.setenv("PROVIDER_MASTER_KEY", TEST_AUTH_SETTINGS["PROVIDER_MASTER_KEY"])
    monkeypatch.setenv(
        "SUPABASE_STORAGE_BUCKET",
        TEST_AUTH_SETTINGS["SUPABASE_STORAGE_BUCKET"],
    )

    settings = Settings.load()

    assert settings.app_env is AppEnvironment.TEST
    assert settings.supabase_url == TEST_AUTH_SETTINGS["SUPABASE_URL"]


def test_database_url_requires_async_postgresql_driver() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        Settings(
            APP_ENV="development",
            DATABASE_URL="sqlite+aiosqlite:///paper_grading.db",
            **TEST_AUTH_SETTINGS,
        )


def test_malformed_database_url_is_a_configuration_error() -> None:
    with pytest.raises(ValidationError, match="格式无效"):
        Settings(
            APP_ENV="production",
            DATABASE_URL="not a database url",
            **TEST_AUTH_SETTINGS,
        )


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
            **TEST_AUTH_SETTINGS,
        )


def test_production_rejects_official_provider_vpn_fake_ip_exception() -> None:
    with pytest.raises(ValidationError, match="生产环境禁止允许供应商 fake-IP"):
        Settings(
            APP_ENV="production",
            DATABASE_URL=(
                "postgresql+asyncpg://postgres.project:secret@"  # pragma: allowlist secret
                "aws-0-test.pooler.supabase.com:5432/postgres?ssl=require"
            ),
            ALLOW_OFFICIAL_PROVIDER_FAKE_IP=True,
            **TEST_AUTH_SETTINGS,
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
            TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )

    assert {item["loc"] for item in error.value.errors()} == {("TEST_MIGRATION_DATABASE_URL",)}


def test_postgres_contract_separates_migration_and_runtime_connections() -> None:
    settings = TestMigrationSettings(
        TEST_MIGRATION_DATABASE_URL=(
            "postgresql+asyncpg://postgres:secret@"  # pragma: allowlist secret
            "db.test-project.supabase.co:5432/postgres?ssl=require"
        ),
        TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
        TEST_SUPABASE_PROJECT_REF="test-project",
        TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
        TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
    )

    assert settings.test_database_url == TEST_RUNTIME_DATABASE_URL


def test_postgres_contract_repr_hides_database_credentials() -> None:
    settings = TestMigrationSettings(
        TEST_MIGRATION_DATABASE_URL=(
            "postgresql+asyncpg://postgres:direct-secret@"  # pragma: allowlist secret
            "db.test-project.supabase.co:5432/postgres?ssl=require"
        ),
        TEST_DATABASE_URL=(
            "postgresql+asyncpg://postgres.test-project:pooler-secret@"  # pragma: allowlist secret
            "aws-0-test.pooler.supabase.com:5432/postgres?ssl=require"
        ),
        TEST_SUPABASE_PROJECT_REF="test-project",
        TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
        TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
    )

    rendered = repr(settings)

    assert "direct-secret" not in rendered
    assert "pooler-secret" not in rendered
    assert "test_migration_database_url" not in rendered
    assert "test_database_url" not in rendered


def test_postgres_contract_runtime_connection_requires_session_pooler() -> None:
    with pytest.raises(ValidationError, match="session pooler 5432"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://postgres:secret@"  # pragma: allowlist secret
                "db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_DATABASE_URL=(
                "postgresql+asyncpg://postgres.test-project:secret@"  # pragma: allowlist secret
                "aws-0-test.pooler.supabase.com:6543/postgres?ssl=require"
            ),
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )


def test_postgres_contract_runtime_username_must_match_project() -> None:
    with pytest.raises(ValidationError, match="用户名必须匹配"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://postgres:secret@"  # pragma: allowlist secret
                "db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_DATABASE_URL=(
                "postgresql+asyncpg://postgres.other-project:secret@"  # pragma: allowlist secret
                "aws-0-test.pooler.supabase.com:5432/postgres?ssl=require"
            ),
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )


def test_postgres_contract_url_requires_async_postgresql_driver() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+asyncpg"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL="postgresql://localhost/paper_grading_test",
            TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )


def test_postgres_contract_requires_destructive_reset_confirmation() -> None:
    with pytest.raises(ValidationError):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )


def test_postgres_contract_project_ref_must_match_url() -> None:
    with pytest.raises(ValidationError, match="project ref"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
            TEST_SUPABASE_PROJECT_REF="other-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )


def test_postgres_contract_rejects_deployment_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = "postgresql+asyncpg://db.same-project.supabase.co:5432/postgres?ssl=require"
    monkeypatch.setenv("MIGRATION_DATABASE_URL", database_url)

    with pytest.raises(ValidationError, match="部署迁移库"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=database_url,
            TEST_DATABASE_URL=(
                "postgresql+asyncpg://postgres.same-project:secret@"  # pragma: allowlist secret
                "aws-0-test.pooler.supabase.com:5432/postgres?ssl=require"
            ),
            TEST_SUPABASE_PROJECT_REF="same-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000002",
        )


def test_postgres_contract_requires_two_auth_users() -> None:
    with pytest.raises(ValidationError) as error:
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
        )

    assert {item["loc"] for item in error.value.errors()} == {
        ("TEST_TEACHER_AUTH_USER_ID",),
        ("TEST_OTHER_AUTH_USER_ID",),
    }


def test_postgres_contract_requires_distinct_auth_users() -> None:
    with pytest.raises(ValidationError, match="必须不同"):
        TestMigrationSettings(
            TEST_MIGRATION_DATABASE_URL=(
                "postgresql+asyncpg://db.test-project.supabase.co:5432/postgres?ssl=require"
            ),
            TEST_DATABASE_URL=TEST_RUNTIME_DATABASE_URL,
            TEST_SUPABASE_PROJECT_REF="test-project",
            TEST_DATABASE_RESET_CONFIRMATION="I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA",
            TEST_TEACHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
            TEST_OTHER_AUTH_USER_ID="00000000-0000-0000-0000-000000000001",
        )


def test_export_worker_does_not_require_provider_master_key() -> None:
    settings = ExportWorkerSettings(
        APP_ENV="test",
        EXPORT_DATABASE_URL=(
            "postgresql+asyncpg://paper_grading_export_worker:secret@"  # pragma: allowlist secret
            "localhost:5432/paper_grading_test"
        ),
        REDIS_URL="redis://127.0.0.1:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SECRET_KEY="server-secret",  # pragma: allowlist secret
        SUPABASE_STORAGE_BUCKET="paper-grading-test",
    )

    assert settings.database_pool_size == 2
    assert settings.database_url.startswith("postgresql+asyncpg://paper_grading_export_worker:")
    assert not hasattr(settings, "provider_master_key")


def test_export_worker_rejects_the_general_application_database_role() -> None:
    with pytest.raises(ValidationError, match="专用最小角色"):
        ExportWorkerSettings(
            APP_ENV="test",
            EXPORT_DATABASE_URL=(
                "postgresql+asyncpg://postgres:secret@"  # pragma: allowlist secret
                "localhost:5432/postgres"
            ),
            REDIS_URL="redis://127.0.0.1:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SECRET_KEY="server-secret",  # pragma: allowlist secret
            SUPABASE_STORAGE_BUCKET="paper-grading-test",
        )


def test_grading_worker_uses_only_its_required_runtime_settings() -> None:
    settings = WorkerSettings(
        APP_ENV="test",
        DATABASE_URL="postgresql+asyncpg://localhost:5432/paper_grading_test",
        REDIS_URL="redis://127.0.0.1:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SECRET_KEY="server-secret",  # pragma: allowlist secret
        SUPABASE_STORAGE_BUCKET="paper-grading-test",
        PROVIDER_MASTER_KEY=TEST_AUTH_SETTINGS["PROVIDER_MASTER_KEY"],
    )

    assert settings.database_pool_size == 5
    assert settings.provider_calls_enabled is False
    assert not hasattr(settings, "supabase_publishable_key")
    assert not hasattr(settings, "auth_invite_redirect_url")
    assert not hasattr(settings, "frontend_origin")


def test_production_grading_worker_requires_its_dedicated_database_role() -> None:
    with pytest.raises(ValidationError, match="专用最小角色"):
        WorkerSettings(
            APP_ENV="production",
            DATABASE_URL=(
                "postgresql+asyncpg://postgres.project-ref:secret@"  # pragma: allowlist secret
                "aws-0-region.pooler.supabase.com:5432/postgres?ssl=require"
            ),
            REDIS_URL="rediss://queue.example.com:6379/0",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_SECRET_KEY="server-secret",  # pragma: allowlist secret
            SUPABASE_STORAGE_BUCKET="paper-grading-test",
            PROVIDER_MASTER_KEY=TEST_AUTH_SETTINGS["PROVIDER_MASTER_KEY"],
        )

    settings = WorkerSettings(
        APP_ENV="production",
        DATABASE_URL=(
            "postgresql+asyncpg://"
            "paper_grading_worker.project-ref:secret@"  # pragma: allowlist secret
            "aws-0-region.pooler.supabase.com:5432/postgres?ssl=require"
        ),
        REDIS_URL="rediss://queue.example.com:6379/0",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SECRET_KEY="server-secret",  # pragma: allowlist secret
        SUPABASE_STORAGE_BUCKET="paper-grading-test",
        PROVIDER_MASTER_KEY=TEST_AUTH_SETTINGS["PROVIDER_MASTER_KEY"],
    )
    assert make_url(settings.database_url).username == "paper_grading_worker.project-ref"


def test_configuration_errors_hide_secret_input_values() -> None:
    canary = "S14LEAK"

    with pytest.raises(ValidationError) as error:
        Settings.model_validate(
            {
                **TEST_AUTH_SETTINGS,
                "APP_ENV": "test",
                "DATABASE_URL": "postgresql+asyncpg://localhost:5432/postgres",
                "REDIS_URL": f"redis://user:{canary}@127.0.0.1/99",
            }
        )

    assert canary not in str(error.value)
