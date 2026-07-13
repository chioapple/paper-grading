"""FastAPI 应用入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.health import router as health_router
from app.config import Settings
from app.readiness import DatabaseReadinessProbe


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用；配置在启动阶段校验，失败时直接终止启动。"""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime_settings = settings or Settings()
        engine = create_async_engine(runtime_settings.database_url, pool_pre_ping=True)
        application.state.settings = runtime_settings
        application.state.readiness_probe = DatabaseReadinessProbe(
            engine=engine,
            timeout_seconds=runtime_settings.readiness_database_timeout_seconds,
        )
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(
        title="Paper Grading API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application


app = create_app()
