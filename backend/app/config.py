"""应用配置。所有必需配置都必须由运行环境显式提供。"""

from enum import StrEnum

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class AppEnvironment(StrEnum):
    """允许的运行环境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """服务启动所需的配置。"""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=None,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: AppEnvironment = Field(validation_alias="APP_ENV")
    database_url: str = Field(validation_alias="DATABASE_URL")
    readiness_database_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        le=30,
        validation_alias="READINESS_DATABASE_TIMEOUT_SECONDS",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """只接受应用实际使用的 PostgreSQL 异步驱动。"""

        try:
            url = make_url(value)
        except ArgumentError as error:
            raise ValueError("DATABASE_URL 格式无效") from error
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL 必须使用 postgresql+asyncpg 驱动")
        if not url.host or not url.database:
            raise ValueError("DATABASE_URL 必须包含数据库主机和库名")
        return value
