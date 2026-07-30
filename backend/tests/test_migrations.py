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
STAGE_TEN_PIPELINE_REVISION = "20260716_0012"
STAGE_TEN_PERMISSION_REVISION = "20260718_0013"
STAGE_TEN_REVISION = "20260718_0014"
STAGE_ELEVEN_SCHEMA_REVISION = "20260719_0015"
STAGE_ELEVEN_REVISION = "20260721_0016"
STAGE_TWELVE_REVISION = "20260722_0017"
STAGE_THIRTEEN_REVISION = "20260726_0018"
STAGE_FOURTEEN_REVISION = "20260728_0019"
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


def test_migration_history_has_one_stage_fourteen_head() -> None:
    scripts = ScriptDirectory.from_config(build_alembic_config())

    assert scripts.get_heads() == [STAGE_FOURTEEN_REVISION]


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
    assert "CREATE TABLE export_items" in sql
    assert "ALTER TABLE public.export_items ENABLE ROW LEVEL SECURITY" in sql
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


def test_stage_ten_batch_pipeline_contract_compiles(
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
        f"{STAGE_NINE_REVISION}:{STAGE_TEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "stage ten requires empty grading job tables" in sql
    assert "ADD COLUMN model_profiles JSONB DEFAULT '{}'::jsonb NOT NULL" in sql
    assert "ADD COLUMN expected_item_count INTEGER NOT NULL" in sql
    assert "ADD COLUMN state_version BIGINT DEFAULT '1' NOT NULL" in sql
    assert "ADD COLUMN dispatch_version INTEGER DEFAULT '1' NOT NULL" in sql
    assert "ADD COLUMN attempt_kind TEXT NOT NULL" in sql
    assert "CREATE UNIQUE INDEX grading_attempts_one_running_idx" in sql
    assert "CREATE UNIQUE INDEX grading_attempts_raw_response_object_key_idx" in sql
    assert "CREATE INDEX grading_job_items_dispatch_idx" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_job_snapshot" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_attempt_history" in sql
    assert "CREATE FUNCTION public.paper_grading_require_ready_job_item" in sql
    assert "CREATE FUNCTION public.paper_grading_protect_job_item" in sql
    assert "(OLD.status = NEW.status) OR" in sql
    assert "job.status IN ('queued', 'running', 'paused')" in sql
    assert "provider.config_version = current_job.provider_config_version" in sql
    assert "CREATE ROLE paper_grading_worker NOLOGIN NOBYPASSRLS" in sql
    assert "REVOKE EXECUTE" in sql
    assert "SET search_path = ''" in sql


def test_stage_ten_batch_pipeline_contract_can_be_rolled_back(
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
        f"{STAGE_TEN_REVISION}:{STAGE_NINE_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP ROLE IF EXISTS paper_grading_worker" in sql
    assert "DROP INDEX grading_attempts_one_running_idx" in sql
    assert "DROP COLUMN model_profiles" in sql
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_protect_job_snapshot" in sql


def test_stage_ten_teacher_batch_permission_repair_compiles(
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
        f"{STAGE_TEN_PIPELINE_REVISION}:{STAGE_TEN_PERMISSION_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_require_ready_job_item()" in sql
    assert "SECURITY INVOKER" in sql
    assert "target_job_status" in sql
    assert "target_submission_status" in sql
    assert "FOR UPDATE" not in sql
    assert "FOR SHARE" not in sql
    assert "GRANT UPDATE" not in sql


def test_stage_ten_deferred_item_count_repair_compiles(
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
        f"{STAGE_TEN_PERMISSION_REVISION}:{STAGE_TEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "CREATE OR REPLACE FUNCTION public.paper_grading_validate_job_item_count()" in sql
    assert "IF TG_TABLE_NAME = 'grading_jobs' THEN" in sql
    assert "ELSIF TG_TABLE_NAME = 'grading_job_items' THEN" in sql
    assert "ELSE NEW.grading_job_id" not in sql


def test_stage_eleven_review_confirmation_contract_compiles(
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
        f"{STAGE_TEN_REVISION}:{STAGE_ELEVEN_SCHEMA_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "ADD COLUMN deduction_results JSONB" in sql
    assert "ADD COLUMN subtotal NUMERIC(10, 4)" in sql
    assert "ADD COLUMN deduction_total NUMERIC(10, 4)" in sql
    assert "CREATE FUNCTION paper_grading_private.save_teacher_review_draft" in sql
    assert "CREATE FUNCTION paper_grading_private.confirm_teacher_reviews" in sql
    assert sql.count("SECURITY DEFINER") >= 2
    assert sql.count("SET search_path = ''") >= 2
    assert "REVOKE INSERT, UPDATE ON TABLE public.teacher_reviews" in sql
    assert "GRANT EXECUTE ON FUNCTION paper_grading_private.save_teacher_review_draft" in sql
    assert "GRANT EXECUTE ON FUNCTION paper_grading_private.confirm_teacher_reviews" in sql
    assert "revision_number = current_review.revision_number + 1" in sql
    assert "TO paper_grading_teacher_api" in sql
    assert "INSERT INTO public.audit_logs" in sql
    assert "status = 'completed'" in sql
    assert "finished_at = transaction_timestamp()" in sql
    assert "status IN ('needs_review', 'failed')" in sql
    assert "status IN ('needs_review', 'completed', 'failed')" not in sql
    assert "current_job.status IN ('queued', 'running', 'paused')" in sql


def test_stage_eleven_review_confirmation_contract_can_be_rolled_back(
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
        f"{STAGE_ELEVEN_SCHEMA_REVISION}:{STAGE_TEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP FUNCTION paper_grading_private.confirm_teacher_reviews" in sql
    assert "DROP FUNCTION paper_grading_private.save_teacher_review_draft" in sql
    assert "DROP COLUMN deduction_total" in sql
    assert "DROP COLUMN subtotal" in sql
    assert "DROP COLUMN deduction_results" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE public.teacher_reviews" in sql


def test_stage_eleven_partial_confirmation_repair_compiles(
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
        f"{STAGE_ELEVEN_SCHEMA_REVISION}:{STAGE_ELEVEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "CREATE FUNCTION public.paper_grading_preserve_active_job_status" in sql
    assert "CREATE TRIGGER grading_jobs_preserve_active_status" in sql
    assert "item.status IN ('queued', 'running')" in sql
    assert "IF OLD.status = 'paused'" in sql
    assert "NEW.status := 'running'" in sql
    assert "job.status = 'needs_review'" in sql
    assert "EXISTS (" in sql


def test_stage_eleven_partial_confirmation_repair_can_be_rolled_back(
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
        f"{STAGE_ELEVEN_REVISION}:{STAGE_ELEVEN_SCHEMA_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "DROP TRIGGER grading_jobs_preserve_active_status" in sql
    assert "DROP FUNCTION public.paper_grading_preserve_active_job_status" in sql


def test_stage_twelve_export_snapshot_and_worker_contract_compiles(
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
        f"{STAGE_ELEVEN_REVISION}:{STAGE_TWELVE_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "CREATE TABLE export_items" in sql
    assert "CREATE ROLE paper_grading_export_worker LOGIN NOINHERIT NOBYPASSRLS" in sql
    assert "REVOKE INSERT ON TABLE public.exports FROM paper_grading_teacher_api" in sql
    assert "DROP POLICY exports_teacher_insert ON public.exports" in sql
    for signature in (
        "paper_grading_private.create_export(uuid, text, text, bytea)",
        "paper_grading_private.claim_export(uuid, uuid, integer)",
        "paper_grading_private.complete_export(uuid, uuid, text, text, bigint, bytea)",
        "paper_grading_private.fail_export(uuid, uuid, text)",
    ):
        assert f"REVOKE EXECUTE ON FUNCTION {signature} FROM PUBLIC" in sql
    assert (
        "GRANT EXECUTE ON FUNCTION paper_grading_private.create_export"
        "(uuid, text, text, bytea) TO paper_grading_teacher_api"
    ) in sql
    assert "export_final_unconfirmed" in sql
    assert "attempt.scoring_round = item.dispatch_version" in sql
    assert "ORDER BY position" in sql
    assert "source_value := 'teacher_confirmed'" in sql
    assert "source_value := 'teacher_draft'" in sql
    assert "source_value := 'ai_suggestion'" in sql
    assert "lease_expires_at <= transaction_timestamp()" in sql
    assert "lease_expires_at > transaction_timestamp()" in sql
    assert "prior_claim_count >= 3" in sql
    assert "export_worker_lost" in sql
    assert "SET search_path = ''" in sql


def test_stage_twelve_export_schema_can_be_rolled_back(
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
        f"{STAGE_TWELVE_REVISION}:{STAGE_ELEVEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "cannot remove stage twelve while export history exists" in sql
    assert "DROP TABLE public.export_items" in sql
    assert "DROP ROLE IF EXISTS paper_grading_export_worker" in sql
    assert "CREATE POLICY exports_teacher_insert ON public.exports" in sql
    assert "GRANT INSERT ON TABLE public.exports TO paper_grading_teacher_api" in sql
    assert "ADD CONSTRAINT exports_audit_metadata_check" in sql


def test_stage_thirteen_quota_retention_and_backup_contract_compiles(
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
        f"{STAGE_TWELVE_REVISION}:{STAGE_THIRTEEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    for table_name in (
        "quota_resource_states",
        "quota_reservations",
        "quota_alerts",
        "retention_objects",
        "backup_runs",
        "backup_restore_runs",
    ):
        assert f"CREATE TABLE {table_name}" in sql
    for function_name in (
        "check_database_growth",
        "reserve_storage_growth",
        "finalize_storage_growth",
        "list_retention_candidates",
        "claim_next_retention_object",
        "revalidate_retention_object",
        "complete_retention_object",
        "fail_retention_object",
    ):
        assert f"CREATE FUNCTION paper_grading_private.{function_name}" in sql
    assert "paper_grading_retention_worker" in sql
    assert "paper_grading_backup_worker" in sql
    assert "SET search_path = ''" in sql
    assert "('database', false), ('storage', false)" in sql
    assert "storage.objects" in sql
    assert "pg_database_size" in sql
    assert "IF current_used IS NULL THEN" in sql
    assert "database_usage_unavailable" in sql
    for invalid_expression in (
        "pg_catalog.coalesce(",
        "pg_catalog.greatest(",
        "pg_catalog.least(",
    ):
        assert invalid_expression not in sql
    assert "s.source_object_key = current_object.object_key" in sql
    assert "s.extracted_object_key = current_object.object_key" in sql
    assert "a.raw_response_object_key = current_object.object_key" in sql


def test_stage_fourteen_grading_worker_login_is_minimal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/paper_grading_test",
    )
    command.upgrade(
        build_alembic_config(),
        f"{STAGE_THIRTEEN_REVISION}:{STAGE_FOURTEEN_REVISION}",
        sql=True,
    )

    sql = capsys.readouterr().out
    assert "ALTER ROLE paper_grading_worker LOGIN NOINHERIT NOBYPASSRLS" in sql
    assert "GRANT USAGE ON SCHEMA paper_grading_private TO paper_grading_worker" in sql
    assert (
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.reserve_storage_growth(text, text, bytea, bigint) "
        "TO paper_grading_worker"
    ) in sql
    assert (
        "GRANT EXECUTE ON FUNCTION "
        "paper_grading_private.finalize_storage_growth(uuid, text) "
        "TO paper_grading_worker"
    ) in sql
    assert "PASSWORD" not in sql
