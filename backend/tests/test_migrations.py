"""Alembic 迁移链路测试。"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).parents[1]
EXPECTED_TABLES = {
    "profiles",
    "provider_configs",
    "assignments",
    "rubric_versions",
    "submissions",
    "grading_jobs",
    "grading_job_items",
    "grading_attempts",
    "teacher_reviews",
    "audit_logs",
    "exports",
}
EXPECTED_STAGE_TWO_FUNCTIONS = {
    "paper_grading_set_updated_at",
    "paper_grading_protect_rubric_history",
    "paper_grading_protect_job_snapshot",
    "paper_grading_reject_history_mutation",
    "paper_grading_require_running_attempt_insert",
    "paper_grading_protect_attempt_history",
    "paper_grading_validate_attempt_score",
    "paper_grading_protect_review_history",
    "paper_grading_validate_review_score",
}
STAGE_FOUR_REVISION = "20260715_0006"
STAGE_FIVE_REVISION = "20260715_0007"
STAGE_SIX_REVISION = "20260716_0008"
STAGE_SEVEN_REVISION = "20260716_0009"
STAGE_EIGHT_REVISION = "20260716_0010"
STAGE_NINE_REVISION = "20260716_0011"
STAGE_FOUR_TEACHER_ROLE = "paper_grading_teacher_api"
STAGE_FOUR_POLICY_COMMANDS = {
    "assignments": ("SELECT", "INSERT", "UPDATE"),
    "rubric_versions": ("SELECT", "INSERT", "UPDATE"),
    "submissions": ("SELECT", "INSERT"),
    "grading_jobs": ("SELECT", "INSERT"),
    "grading_job_items": ("SELECT", "INSERT"),
    "grading_attempts": ("SELECT",),
    "teacher_reviews": ("SELECT", "INSERT", "UPDATE"),
    "audit_logs": ("SELECT",),
    "exports": ("SELECT", "INSERT"),
}


def build_alembic_config() -> Config:
    """创建指向项目迁移目录的 Alembic 配置。"""

    return Config(str(BACKEND_ROOT / "alembic.ini"))


def test_migration_history_has_one_stage_eight_head() -> None:
    scripts = ScriptDirectory.from_config(build_alembic_config())

    assert scripts.get_heads() == [STAGE_NINE_REVISION]


def test_offline_upgrade_compiles_every_domain_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(build_alembic_config(), "head", sql=True)

    sql = capsys.readouterr().out
    for table_name in EXPECTED_TABLES:
        assert f"CREATE TABLE {table_name}" in sql
        assert f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY" in sql
    for trigger_name in {
        "profiles_set_updated_at",
        "provider_configs_set_updated_at",
        "assignments_set_updated_at",
        "audit_logs_reject_mutation",
        "grading_attempts_require_running_insert",
        "grading_attempts_protect_history",
        "teacher_reviews_protect_history",
        "grading_attempts_validate_rubric_score",
        "teacher_reviews_validate_attempt_score",
        "rubric_versions_protect_history",
        "grading_jobs_protect_snapshot",
        "profiles_create_invited_teacher",
    }:
        assert f"CREATE TRIGGER {trigger_name}" in sql


def test_stage_four_migration_enforces_active_teacher_isolation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(build_alembic_config(), STAGE_FOUR_REVISION, sql=True)

    sql = capsys.readouterr().out
    assert f"CREATE ROLE {STAGE_FOUR_TEACHER_ROLE} NOLOGIN NOINHERIT NOBYPASSRLS" in sql
    assert f"GRANT {STAGE_FOUR_TEACHER_ROLE} TO postgres" in sql
    for table_name in EXPECTED_TABLES:
        assert f"ALTER TABLE public.{table_name} FORCE ROW LEVEL SECURITY" in sql
        assert f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM anon" in sql
        assert f"REVOKE ALL PRIVILEGES ON TABLE public.{table_name} FROM authenticated" in sql
    for table_name in {"assignments", "rubric_versions", "teacher_reviews"}:
        assert f"CREATE POLICY {table_name}_teacher_update ON public.{table_name}" in sql
    for table_name in {"submissions", "grading_jobs", "grading_job_items", "exports"}:
        assert f"CREATE POLICY {table_name}_teacher_insert ON public.{table_name}" in sql
    assert "CREATE POLICY profiles_teacher_select ON public.profiles" in sql
    for table_name, operations in STAGE_FOUR_POLICY_COMMANDS.items():
        for operation in operations:
            assert (
                f"CREATE POLICY {table_name}_teacher_{operation.lower()} "
                f"ON public.{table_name} FOR {operation} TO {STAGE_FOUR_TEACHER_ROLE}" in sql
            )
    assert f"GRANT SELECT ON TABLE public.profiles TO {STAGE_FOUR_TEACHER_ROLE}" in sql
    assert "REVOKE ALL PRIVILEGES ON TABLE public.provider_configs FROM authenticated" in sql
    assert "CREATE POLICY provider_configs" not in sql
    assert f"TO {STAGE_FOUR_TEACHER_ROLE}" in sql
    assert "CREATE SCHEMA IF NOT EXISTS paper_grading_private" in sql
    assert "CREATE FUNCTION paper_grading_private.current_active_teacher_id()" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = ''" in sql
    assert "profile.status = 'active'" in sql
    assert "profile.role = 'teacher'" in sql
    assert "owner_id = (SELECT paper_grading_private.current_active_teacher_id())" in sql


def test_stage_two_functions_have_a_fixed_empty_search_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(build_alembic_config(), "20260714_0003", sql=True)

    sql = capsys.readouterr().out
    assert sql.count("SET search_path = ''") == len(EXPECTED_STAGE_TWO_FUNCTIONS)


def test_stage_two_internal_functions_are_not_exposed_to_api_roles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(build_alembic_config(), "20260714_0003", sql=True)

    sql = capsys.readouterr().out
    for function_name in EXPECTED_STAGE_TWO_FUNCTIONS:
        assert f"REVOKE EXECUTE ON FUNCTION public.{function_name}() FROM PUBLIC" in sql
    assert "to_regprocedure('public.rls_auto_enable()')" in sql
    for role_name in {"anon", "authenticated", "service_role"}:
        assert f"'{role_name}'" in sql


def test_offline_stage_two_downgrade_compiles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.downgrade(
        build_alembic_config(),
        "20260714_0003:20260713_0001",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP TRIGGER IF EXISTS grading_attempts_require_running_insert" in sql
    assert "DROP TABLE profiles" in sql


def test_stage_three_profile_trigger_ignores_non_invited_auth_users(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(build_alembic_config(), "20260714_0004", sql=True)

    sql = capsys.readouterr().out
    assert "IF NEW.invited_at IS NULL THEN" in sql
    assert (
        "REVOKE EXECUTE ON FUNCTION public.paper_grading_create_invited_teacher() FROM PUBLIC"
        in sql
    )
    for role_name in {"anon", "authenticated", "service_role"}:
        assert f"'{role_name}'" in sql
    assert "public.paper_grading_create_invited_teacher() FROM %I" in sql


def test_stage_three_profile_trigger_handles_supabase_two_step_invites(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Supabase 先插入用户、再写入 invited_at 时仍会创建 profile。"""

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(build_alembic_config(), "20260714_0005", sql=True)

    sql = capsys.readouterr().out
    assert "CREATE TRIGGER profiles_create_invited_teacher_on_invite" in sql
    assert "AFTER UPDATE OF invited_at ON auth.users" in sql
    assert "WHEN (OLD.invited_at IS NULL AND NEW.invited_at IS NOT NULL)" in sql


def test_stage_three_two_step_invite_trigger_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.downgrade(
        build_alembic_config(),
        "20260714_0005:20260714_0004",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP TRIGGER profiles_create_invited_teacher_on_invite ON auth.users" in sql


def test_stage_four_rls_migration_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.downgrade(
        build_alembic_config(),
        "20260715_0006:20260714_0005",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP POLICY profiles_teacher_select ON public.profiles" in sql
    assert "DROP FUNCTION paper_grading_private.current_active_teacher_id()" in sql
    assert "ALTER TABLE public.profiles NO FORCE ROW LEVEL SECURITY" in sql
    assert "DROP SCHEMA paper_grading_private" in sql
    assert "REVOKE paper_grading_teacher_api FROM postgres" in sql
    assert "DROP ROLE paper_grading_teacher_api" in sql


def test_stage_five_provider_test_is_bound_to_the_current_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.upgrade(build_alembic_config(), STAGE_FIVE_REVISION, sql=True)

    sql = capsys.readouterr().out
    assert "ADD COLUMN config_version BIGINT DEFAULT '1' NOT NULL" in sql
    assert "ADD COLUMN tested_config_version BIGINT" in sql
    assert "UPDATE public.provider_configs" in sql
    assert "SET status = 'draft', tested_at = NULL" in sql
    assert "ALTER TABLE provider_configs DROP CONSTRAINT provider_configs_enabled_check" in sql
    assert "ALTER TABLE provider_configs DROP CONSTRAINT provider_configs_key_material_check" in sql
    assert "provider_configs_provider_configs_" not in sql
    assert "_check_check" not in sql
    assert "tested_config_version = config_version" in sql
    assert "octet_length(api_key_nonce) = 12" in sql
    assert "CREATE FUNCTION public.paper_grading_invalidate_provider_test()" in sql
    assert "CREATE TRIGGER provider_configs_invalidate_test" in sql
    assert "NEW.tested_config_version := NULL" in sql
    assert "NEW.status := 'draft'" in sql


def test_stage_five_provider_hardening_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.downgrade(
        build_alembic_config(),
        "20260715_0007:20260715_0006",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP TRIGGER IF EXISTS provider_configs_invalidate_test" in sql
    assert "DROP FUNCTION IF EXISTS public.paper_grading_invalidate_provider_test()" in sql
    assert (
        "ALTER TABLE provider_configs DROP CONSTRAINT provider_configs_default_model_check" in sql
    )
    assert "ALTER TABLE provider_configs ADD CONSTRAINT provider_configs_enabled_check" in sql
    assert "provider_configs_provider_configs_" not in sql
    assert "_check_check" not in sql
    assert "DROP COLUMN tested_config_version" in sql
    assert "DROP COLUMN config_version" in sql


def test_stage_six_rubric_contract_compiles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.upgrade(build_alembic_config(), STAGE_SIX_REVISION, sql=True)

    sql = capsys.readouterr().out
    assert "ADD COLUMN provider_config_id UUID" in sql
    assert "ADD COLUMN model TEXT" in sql
    assert "CREATE UNIQUE INDEX rubric_versions_one_draft_idx" in sql
    assert "CREATE UNIQUE INDEX rubric_versions_one_confirmed_idx" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_rubric_history()" in sql
    assert "NEW.provider_config_id" in sql
    assert "OLD.provider_config_id" in sql
    assert "NEW.model" in sql
    assert "OLD.model" in sql
    assert "ready assignment cannot lose its confirmed rubric" in sql
    assert "CREATE FUNCTION public.paper_grading_valid_structured_rubric(" in sql
    assert "SET search_path = ''" in sql
    assert "GRANT EXECUTE ON FUNCTION public.paper_grading_valid_structured_rubric" in sql
    assert "TO paper_grading_teacher_api" in sql
    assert "CREATE TRIGGER assignments_require_confirmed_rubric" in sql
    assert "CREATE TRIGGER grading_jobs_require_confirmed_rubric" in sql
    assert "ready assignment without confirmed rubric exists" in sql
    assert "grading job with unconfirmed rubric exists" in sql


def test_stage_six_rubric_contract_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.downgrade(
        build_alembic_config(),
        "20260716_0008:20260715_0007",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP TRIGGER grading_jobs_require_confirmed_rubric" in sql
    assert "DROP TRIGGER assignments_require_confirmed_rubric" in sql
    assert "DROP FUNCTION public.paper_grading_valid_structured_rubric" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_rubric_history()" in sql
    assert "DROP INDEX rubric_versions_one_confirmed_idx" in sql
    assert "DROP INDEX rubric_versions_one_draft_idx" in sql
    assert "DROP COLUMN model" in sql
    assert "DROP COLUMN provider_config_id" in sql


def test_stage_seven_submission_contract_compiles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.upgrade(build_alembic_config(), STAGE_SEVEN_REVISION, sql=True)

    sql = capsys.readouterr().out
    assert "invalid existing submission state" in sql
    assert "ALTER TABLE submissions DROP CONSTRAINT submissions_ready_check" in sql
    assert "ADD CONSTRAINT submissions_state_check" in sql
    assert "ADD CONSTRAINT submissions_object_keys_check" in sql
    assert "ADD CONSTRAINT submissions_original_filename_check" in sql
    assert "ADD CONSTRAINT submissions_source_object_key_key UNIQUE" in sql
    assert "CREATE UNIQUE INDEX submissions_extracted_object_key_idx" in sql
    assert "CREATE FUNCTION paper_grading_private.transition_submission" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = ''" in sql
    assert "current_submission.status = 'failed' AND target_status = 'uploaded'" in sql
    assert "REVOKE EXECUTE ON FUNCTION paper_grading_private.transition_submission" in sql
    assert "GRANT EXECUTE ON FUNCTION paper_grading_private.transition_submission" in sql
    assert "TO paper_grading_teacher_api" in sql
    assert "GRANT UPDATE ON TABLE public.submissions" not in sql


def test_stage_seven_submission_contract_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.downgrade(
        build_alembic_config(),
        "20260716_0009:20260716_0008",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP FUNCTION paper_grading_private.transition_submission" in sql
    assert "DROP INDEX submissions_extracted_object_key_idx" in sql
    assert "DROP CONSTRAINT submissions_source_object_key_key" in sql
    assert "DROP CONSTRAINT submissions_object_keys_check" in sql
    assert "ADD CONSTRAINT submissions_ready_check" in sql


def test_stage_eight_grading_snapshots_compile(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.upgrade(
        build_alembic_config(),
        f"{STAGE_SEVEN_REVISION}:{STAGE_EIGHT_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "stage eight requires empty grading job tables" in sql
    assert "ADD COLUMN result_schema_version TEXT NOT NULL" in sql
    assert "ADD COLUMN result_schema_hash BYTEA NOT NULL" in sql
    assert "ADD COLUMN rubric_hash BYTEA NOT NULL" in sql
    assert "ADD COLUMN request_version TEXT NOT NULL" in sql
    assert "ALTER TABLE grading_jobs DROP CONSTRAINT grading_jobs_snapshot_check" in sql
    assert "ADD CONSTRAINT grading_jobs_snapshot_check" in sql
    assert "ALTER TABLE grading_attempts DROP CONSTRAINT grading_attempts_request_check" in sql
    assert "ADD CONSTRAINT grading_attempts_request_check" in sql
    assert "NEW.result_schema_version" in sql
    assert "NEW.result_schema_hash" in sql
    assert "NEW.rubric_hash" in sql
    assert "NEW.request_version" in sql
    assert sql.count("SET search_path = ''") == 2
    assert (
        "REVOKE EXECUTE ON FUNCTION public.paper_grading_protect_job_snapshot() FROM PUBLIC" in sql
    )
    assert (
        "REVOKE EXECUTE ON FUNCTION public.paper_grading_protect_attempt_history() FROM PUBLIC"
        in sql
    )
    assert sql.count("WHERE rolname IN ('anon', 'authenticated', 'service_role')") == 2


def test_stage_eight_grading_snapshots_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.downgrade(
        build_alembic_config(),
        "20260716_0010:20260716_0009",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP COLUMN request_version" in sql
    assert "DROP COLUMN rubric_hash" in sql
    assert "DROP COLUMN result_schema_hash" in sql
    assert "DROP COLUMN result_schema_version" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_job_snapshot" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_attempt_history" in sql
    assert "octet_length(request_hash) = 32" in sql


def test_stage_nine_provider_call_snapshots_compile(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.upgrade(
        build_alembic_config(),
        f"{STAGE_EIGHT_REVISION}:{STAGE_NINE_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "stage nine requires empty grading job tables" in sql
    assert "ADD COLUMN provider_config_version INTEGER NOT NULL" in sql
    assert "ADD COLUMN result_schema JSONB NOT NULL" in sql
    assert "ADD COLUMN raw_response_sha256 BYTEA" in sql
    assert "jsonb_typeof(result_schema) = 'object'" in sql
    assert "provider_config_version > 0" in sql
    assert "octet_length(raw_response_sha256) = 32" in sql
    assert "NEW.provider_config_version" in sql
    assert "NEW.result_schema" in sql


def test_stage_nine_provider_call_snapshots_can_be_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )

    command.downgrade(
        build_alembic_config(),
        f"{STAGE_NINE_REVISION}:{STAGE_EIGHT_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP COLUMN raw_response_sha256" in sql
    assert "DROP COLUMN result_schema" in sql
    assert "DROP COLUMN provider_config_version" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_job_snapshot" in sql
    assert "NEW.result_schema_version" in sql
