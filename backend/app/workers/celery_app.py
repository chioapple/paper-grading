"""Celery Worker、周期投递和过期租约收口入口。"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx
from celery import Celery
from kombu import Queue  # type: ignore[import-untyped]

from app.config import WorkerSettings
from app.db import Database
from app.monitoring.repository import SqlAlchemyQuotaRepository
from app.providers.connection import ProviderBaseUrlPolicy
from app.providers.http import HttpCoreProviderAdapterClient
from app.providers.registry import build_provider_adapter_registry
from app.security.encryption import ApiKeyCipher
from app.storage.supabase import SupabaseObjectStorage
from app.workers.dispatcher import GRADE_ITEM_TASK, CeleryGradingQueue, dispatch_ready_items
from app.workers.repository import SqlAlchemyGradingJobRepository
from app.workers.tasks import GradingAttemptRunner

settings = WorkerSettings.load()
logging.getLogger("httpx").setLevel(logging.WARNING)
GRADING_QUEUE = "paper_grading.grading"
MAINTENANCE_QUEUE = "paper_grading.maintenance"
DISPATCH_TASK = "paper_grading.dispatch_ready_items"
EXPIRE_TASK = "paper_grading.expire_stale_attempts"
MAINTENANCE_INTERVAL_SECONDS = 30.0
MAINTENANCE_EXPIRES_SECONDS = 25.0

celery_app = Celery("paper_grading", broker=settings.redis_url)
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
    broker_transport_options={
        "visibility_timeout": 600,
        "queue_order_strategy": "round_robin",
    },
    task_queues=(Queue(GRADING_QUEUE), Queue(MAINTENANCE_QUEUE)),
    task_routes={
        GRADE_ITEM_TASK: {"queue": GRADING_QUEUE},
        DISPATCH_TASK: {"queue": MAINTENANCE_QUEUE},
        EXPIRE_TASK: {"queue": MAINTENANCE_QUEUE},
    },
    task_annotations={
        DISPATCH_TASK: {"soft_time_limit": 20, "time_limit": 25},
        EXPIRE_TASK: {"soft_time_limit": 20, "time_limit": 25},
    },
    beat_schedule={
        "dispatch-ready-grading-items": {
            "task": DISPATCH_TASK,
            "schedule": MAINTENANCE_INTERVAL_SECONDS,
            "options": {
                "queue": MAINTENANCE_QUEUE,
                "expires": MAINTENANCE_EXPIRES_SECONDS,
            },
        },
        "expire-stale-grading-attempts": {
            "task": EXPIRE_TASK,
            "schedule": MAINTENANCE_INTERVAL_SECONDS,
            "options": {
                "queue": MAINTENANCE_QUEUE,
                "expires": MAINTENANCE_EXPIRES_SECONDS,
            },
        },
    },
)


async def _run_grading_item(item_id: UUID, dispatch_version: int) -> str:
    if not settings.provider_calls_enabled:
        raise RuntimeError("provider_calls_disabled")
    database = Database.from_settings(settings)
    try:
        async with httpx.AsyncClient(
            timeout=settings.supabase_storage_timeout_seconds,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            trust_env=False,
        ) as storage_client:
            repository = SqlAlchemyGradingJobRepository(database)
            runner = GradingAttemptRunner(
                repository=repository,
                storage=SupabaseObjectStorage.from_settings(
                    settings,
                    storage_client,
                    quota=SqlAlchemyQuotaRepository(database),
                ),
                adapters=build_provider_adapter_registry(
                    url_policy=ProviderBaseUrlPolicy(
                        allow_official_fake_ip=settings.allow_official_provider_fake_ip,
                    ),
                    http_client=HttpCoreProviderAdapterClient(),
                ),
                cipher=ApiKeyCipher.from_base64_master_key(
                    settings.provider_master_key.get_secret_value()
                ),
                now=lambda: datetime.now(UTC),
            )
            return await runner.run(item_id, dispatch_version)
    finally:
        await database.dispose()


async def _dispatch() -> int:
    if not settings.provider_calls_enabled:
        return 0
    database = Database.from_settings(settings)
    try:
        repository = SqlAlchemyGradingJobRepository(database)
        return await dispatch_ready_items(repository, CeleryGradingQueue())
    finally:
        await database.dispose()


async def _expire() -> int:
    database = Database.from_settings(settings)
    try:
        return await SqlAlchemyGradingJobRepository(database).expire_stale_attempts()
    finally:
        await database.dispose()


@celery_app.task(name=GRADE_ITEM_TASK)  # type: ignore[untyped-decorator]
def grade_item(item_id: str, dispatch_version: int) -> str:
    return asyncio.run(_run_grading_item(UUID(item_id), dispatch_version))


@celery_app.task(name=DISPATCH_TASK)  # type: ignore[untyped-decorator]
def dispatch_ready_grading_items() -> int:
    return asyncio.run(_dispatch())


@celery_app.task(name=EXPIRE_TASK)  # type: ignore[untyped-decorator]
def expire_stale_grading_attempts() -> int:
    return asyncio.run(_expire())
