"""不加载供应商密钥的独立导出 Celery 应用。"""

import asyncio
import logging
from uuid import UUID

import httpx
from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]
from celery import Celery
from celery.app.task import Task
from kombu import Queue  # type: ignore[import-untyped]
from sqlalchemy.exc import SQLAlchemyError

from app.config import ExportWorkerSettings
from app.db import Database
from app.export.dispatcher import EXPORT_QUEUE, EXPORT_TASK
from app.export.tasks import ExportRetryRequired, ExportRunner
from app.export.worker_repository import EXPORT_LEASE_SECONDS, SqlAlchemyExportWorkerRepository
from app.monitoring.repository import SqlAlchemyQuotaRepository
from app.storage.supabase import SupabaseObjectStorage

settings = ExportWorkerSettings.load()
logging.getLogger("httpx").setLevel(logging.WARNING)
EXPORT_SOFT_TIME_LIMIT_SECONDS = 540
EXPORT_HARD_TIME_LIMIT_SECONDS = 570
DATABASE_RETRY_SECONDS = 30
SOFT_TIMEOUT_RETRY_SECONDS = EXPORT_LEASE_SECONDS - EXPORT_SOFT_TIME_LIMIT_SECONDS + 1
MAX_SOFT_TIMEOUT_ATTEMPTS = 2
celery_app = Celery("paper_grading_exports", broker=settings.redis_url)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_backend=None,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    enable_utc=True,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 600},
    task_queues=(Queue(EXPORT_QUEUE),),
    task_routes={EXPORT_TASK: {"queue": EXPORT_QUEUE}},
    task_annotations={
        EXPORT_TASK: {
            "soft_time_limit": EXPORT_SOFT_TIME_LIMIT_SECONDS,
            "time_limit": EXPORT_HARD_TIME_LIMIT_SECONDS,
        }
    },
)


async def _run_export(export_id: UUID, *, fail_timed_out: bool = False) -> str:
    database = Database.from_settings(settings)
    try:
        async with httpx.AsyncClient(
            timeout=settings.supabase_storage_timeout_seconds,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
            trust_env=False,
        ) as client:
            runner = ExportRunner(
                repository=SqlAlchemyExportWorkerRepository(database),
                storage=SupabaseObjectStorage.from_settings(
                    settings,
                    client,
                    quota=SqlAlchemyQuotaRepository(database),
                ),
            )
            if fail_timed_out:
                return await runner.fail_timed_out(export_id)
            return await runner.run(export_id)
    finally:
        await database.dispose()


@celery_app.task(name=EXPORT_TASK, bind=True, max_retries=None)  # type: ignore[untyped-decorator]
def generate_export(task: Task, export_id: str, soft_timeout_count: int = 0) -> str:
    try:
        return asyncio.run(
            _run_export(
                UUID(export_id),
                fail_timed_out=soft_timeout_count >= MAX_SOFT_TIMEOUT_ATTEMPTS,
            )
        )
    except ExportRetryRequired as error:
        raise task.retry(exc=error, countdown=error.countdown_seconds) from error
    except SQLAlchemyError as error:
        raise task.retry(exc=error, countdown=DATABASE_RETRY_SECONDS) from error
    except SoftTimeLimitExceeded as error:
        raise task.retry(
            exc=error,
            countdown=SOFT_TIMEOUT_RETRY_SECONDS,
            kwargs={"soft_timeout_count": soft_timeout_count + 1},
        ) from error
