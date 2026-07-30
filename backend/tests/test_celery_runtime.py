"""阶段十 Celery 运行时的队列隔离行为测试。"""

import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from pytest import MonkeyPatch
from sqlalchemy.exc import SQLAlchemyError

from app.export.tasks import ExportRetryRequired
from tests.auth_settings import TEST_AUTH_SETTINGS


def load_celery_module(monkeypatch: MonkeyPatch) -> ModuleType:
    """使用完整测试配置重新加载 Celery 入口。"""

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://paper_grading:secret@"  # pragma: allowlist secret
        "127.0.0.1:5432/paper_grading_test",
    )
    for name, value in TEST_AUTH_SETTINGS.items():
        monkeypatch.setenv(name, str(value))
    sys.modules.pop("app.workers.celery_app", None)
    return importlib.import_module("app.workers.celery_app")


def load_export_celery_module(monkeypatch: MonkeyPatch) -> ModuleType:
    """独立导出入口不得依赖供应商主密钥。"""

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "EXPORT_DATABASE_URL",
        "postgresql+asyncpg://paper_grading_export_worker:secret@"  # pragma: allowlist secret
        "127.0.0.1:5432/paper_grading_test",
    )
    for name, value in TEST_AUTH_SETTINGS.items():
        if name != "PROVIDER_MASTER_KEY":
            monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("PROVIDER_MASTER_KEY", raising=False)
    sys.modules.pop("app.export.celery_app", None)
    return importlib.import_module("app.export.celery_app")


def routed_queue_name(module: ModuleType, task_name: str) -> str:
    """读取 Celery 对任务公开给 broker 的最终队列。"""

    route = module.celery_app.amqp.router.route({}, task_name, args=(), kwargs={})
    return str(route["queue"].name)


def test_grading_tasks_cannot_be_starved_by_periodic_maintenance(
    monkeypatch: MonkeyPatch,
) -> None:
    module = load_celery_module(monkeypatch)

    assert routed_queue_name(module, module.GRADE_ITEM_TASK) == "paper_grading.grading"
    assert (
        routed_queue_name(module, "paper_grading.dispatch_ready_items")
        == "paper_grading.maintenance"
    )
    assert (
        routed_queue_name(module, "paper_grading.expire_stale_attempts")
        == "paper_grading.maintenance"
    )


def test_periodic_maintenance_cannot_accumulate_faster_than_it_runs(
    monkeypatch: MonkeyPatch,
) -> None:
    module = load_celery_module(monkeypatch)

    assert module.celery_app.conf.broker_transport_options["queue_order_strategy"] == "round_robin"
    for task in module.celery_app.conf.beat_schedule.values():
        assert task["schedule"] == 30.0
        assert task["options"] == {
            "queue": "paper_grading.maintenance",
            "expires": 25.0,
        }
    for task_name in (module.DISPATCH_TASK, module.EXPIRE_TASK):
        assert module.celery_app.conf.task_annotations[task_name] == {
            "soft_time_limit": 20,
            "time_limit": 25,
        }


def test_worker_does_not_log_private_storage_object_paths(
    monkeypatch: MonkeyPatch,
) -> None:
    load_celery_module(monkeypatch)

    assert logging.getLogger("httpx").level == logging.WARNING


def test_worker_processes_isolate_grading_from_maintenance_execution_slots() -> None:
    from app.workers.supervisor import worker_commands

    grading_command, maintenance_command = worker_commands("/test/python")

    assert grading_command[:3] == ("/test/python", "-m", "celery")
    assert "--queues=paper_grading.grading" in grading_command
    assert "--queues=paper_grading.maintenance" not in grading_command
    assert "--beat" not in grading_command

    assert maintenance_command[:3] == ("/test/python", "-m", "celery")
    assert "--queues=paper_grading.maintenance" in maintenance_command
    assert "--queues=paper_grading.grading" not in maintenance_command
    assert "--beat" in maintenance_command


def test_local_grading_worker_uses_the_isolated_worker_supervisor() -> None:
    runner = (Path(__file__).parents[2] / "infra/local/run-component.sh").read_text()
    grading = runner.split("  grading)", 1)[1].split("  ;;", 1)[0]

    assert "app.workers.supervisor" in grading
    assert "--beat" not in grading


def test_export_worker_has_its_own_queue_and_no_beat(monkeypatch: MonkeyPatch) -> None:
    module = load_export_celery_module(monkeypatch)

    assert routed_queue_name(module, module.EXPORT_TASK) == "paper_grading.exports"
    assert module.celery_app.conf.beat_schedule == {}
    assert module.celery_app.conf.task_annotations[module.EXPORT_TASK] == {
        "soft_time_limit": 540,
        "time_limit": 570,
    }
    assert module.generate_export.max_retries is None


@pytest.mark.parametrize(
    ("error", "expected_countdown"),
    [
        (ExportRetryRequired(321), 321),
        (SQLAlchemyError("database unavailable"), 30),
    ],
)
def test_export_worker_retries_recoverable_claim_and_database_failures(
    monkeypatch: MonkeyPatch,
    error: Exception,
    expected_countdown: int,
) -> None:
    module = load_export_celery_module(monkeypatch)

    async def fail(_export_id: UUID, *, fail_timed_out: bool = False) -> str:
        assert fail_timed_out is False
        raise error

    retries: list[tuple[Exception, int]] = []

    def retry(*, exc: Exception, countdown: int) -> None:
        retries.append((exc, countdown))
        raise RuntimeError("retry_scheduled")

    monkeypatch.setattr(module, "_run_export", fail)
    monkeypatch.setattr(module.generate_export, "retry", retry)

    with pytest.raises(RuntimeError, match="retry_scheduled"):
        module.generate_export.run("11111111-1111-4111-8111-111111111111")

    assert retries == [(error, expected_countdown)]


def test_export_worker_stops_regenerating_after_two_soft_timeouts(
    monkeypatch: MonkeyPatch,
) -> None:
    module = load_export_celery_module(monkeypatch)
    calls: list[bool] = []

    async def run(_export_id: UUID, *, fail_timed_out: bool = False) -> str:
        calls.append(fail_timed_out)
        if fail_timed_out:
            return "export_workbook_timeout"
        raise SoftTimeLimitExceeded

    retries: list[tuple[Exception, int, dict[str, int]]] = []

    def retry(
        *,
        exc: Exception,
        countdown: int,
        kwargs: dict[str, int],
    ) -> None:
        retries.append((exc, countdown, kwargs))
        raise RuntimeError("retry_scheduled")

    monkeypatch.setattr(module, "_run_export", run)
    monkeypatch.setattr(module.generate_export, "retry", retry)

    with pytest.raises(RuntimeError, match="retry_scheduled"):
        module.generate_export.run("11111111-1111-4111-8111-111111111111", 0)
    assert retries[0][1:] == (61, {"soft_timeout_count": 1})

    assert (
        module.generate_export.run(
            "11111111-1111-4111-8111-111111111111",
            module.MAX_SOFT_TIMEOUT_ATTEMPTS,
        )
        == "export_workbook_timeout"
    )
    assert calls == [False, True]


def test_local_export_worker_does_not_receive_provider_master_key() -> None:
    runner = (Path(__file__).parents[2] / "infra/local/run-component.sh").read_text()
    export = runner.split("  export)", 1)[1].split("  ;;", 1)[0]

    assert "--queues=paper_grading.exports" in export
    assert "unset PROVIDER_MASTER_KEY" in export
    assert "unset DATABASE_URL" in export
