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


def build_alembic_config() -> Config:
    """创建指向项目迁移目录的 Alembic 配置。"""

    return Config(str(BACKEND_ROOT / "alembic.ini"))


def test_migration_history_has_one_stage_two_head() -> None:
    scripts = ScriptDirectory.from_config(build_alembic_config())

    assert scripts.get_heads() == ["20260713_0002"]


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
        "grading_attempts_protect_history",
        "teacher_reviews_protect_history",
        "grading_attempts_validate_rubric_score",
        "teacher_reviews_validate_attempt_score",
        "rubric_versions_protect_history",
        "grading_jobs_protect_snapshot",
    }:
        assert f"CREATE TRIGGER {trigger_name}" in sql
