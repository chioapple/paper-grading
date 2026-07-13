"""应用配置。所有必需配置都必须由运行环境显式提供。"""

import os
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class AppEnvironment(StrEnum):
    """允许的运行环境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


def validate_async_postgresql_url(value: str, variable_name: str) -> str:
    """校验 SQLAlchemy 使用的 PostgreSQL 异步连接地址。"""

    try:
        url = make_url(value)
    except ArgumentError as error:
        raise ValueError(f"{variable_name} 格式无效") from error
    if url.drivername != "postgresql+asyncpg":
        raise ValueError(f"{variable_name} 必须使用 postgresql+asyncpg 驱动")
    if not url.host or not url.database:
        raise ValueError(f"{variable_name} 必须包含数据库主机和库名")
    if url.host.lower() not in {"localhost", "127.0.0.1", "::1"}:
        ssl_mode = url.query.get("ssl")
        if ssl_mode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError(f"远程 {variable_name} 必须显式设置 ssl=require 或更严格模式")
    return value


def validate_supabase_direct_url(value: str, variable_name: str) -> str:
    """远程迁移只允许 Supabase direct 端点。"""

    url = make_url(value)
    host = url.host.lower() if url.host else ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        return value
    if not host.startswith("db.") or not host.endswith(".supabase.co"):
        raise ValueError(f"远程 {variable_name} 必须使用 Supabase direct 地址")
    if url.port not in {None, 5432}:
        raise ValueError(f"远程 {variable_name} direct 地址必须使用 5432 端口")
    return value


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
    database_pool_size: int = Field(default=5, ge=1, le=10, validation_alias="DATABASE_POOL_SIZE")
    database_pool_timeout_seconds: float = Field(
        default=5.0,
        gt=0,
        le=30,
        validation_alias="DATABASE_POOL_TIMEOUT_SECONDS",
    )
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

        return validate_async_postgresql_url(value, "DATABASE_URL")

    @model_validator(mode="after")
    def validate_production_pooler(self) -> Self:
        """生产应用固定使用 Supavisor session pooler 5432。"""

        if self.app_env is not AppEnvironment.PRODUCTION:
            return self
        url = make_url(self.database_url)
        host = url.host.lower() if url.host else ""
        if not host.endswith(".pooler.supabase.com") or url.port != 5432:
            raise ValueError("生产 DATABASE_URL 必须使用 Supavisor session pooler 5432")
        return self


class MigrationSettings(BaseSettings):
    """迁移任务配置；禁止回退使用应用连接池地址。"""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=None,
        extra="ignore",
        populate_by_name=True,
    )

    migration_database_url: str = Field(validation_alias="MIGRATION_DATABASE_URL")

    @field_validator("migration_database_url")
    @classmethod
    def validate_migration_database_url(cls, value: str) -> str:
        """迁移只接受显式提供的 PostgreSQL 直连地址。"""

        validated = validate_async_postgresql_url(value, "MIGRATION_DATABASE_URL")
        return validate_supabase_direct_url(validated, "MIGRATION_DATABASE_URL")


class TestMigrationSettings(BaseSettings):
    """真实约束验收配置；禁止复用部署迁移地址。"""

    __test__ = False
    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=None,
        extra="ignore",
        populate_by_name=True,
    )

    test_migration_database_url: str = Field(validation_alias="TEST_MIGRATION_DATABASE_URL")
    test_supabase_project_ref: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9-]+$",
        validation_alias="TEST_SUPABASE_PROJECT_REF",
    )
    test_database_reset_confirmation: Literal["I_UNDERSTAND_THIS_DELETES_STAGE_2_DATA"] = Field(
        validation_alias="TEST_DATABASE_RESET_CONFIRMATION"
    )

    @field_validator("test_migration_database_url")
    @classmethod
    def validate_test_migration_database_url(cls, value: str) -> str:
        """真实验收只接受显式提供的独立 PostgreSQL 测试库。"""

        validated = validate_async_postgresql_url(value, "TEST_MIGRATION_DATABASE_URL")
        direct_url = validate_supabase_direct_url(validated, "TEST_MIGRATION_DATABASE_URL")
        host = make_url(direct_url).host or ""
        if host.lower() in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("TEST_MIGRATION_DATABASE_URL 必须指向独立 Supabase 测试项目")
        return direct_url

    @model_validator(mode="after")
    def validate_destructive_test_target(self) -> Self:
        """确认测试项目标识，并拒绝部署迁移库。"""

        test_url = make_url(self.test_migration_database_url)
        test_host = (test_url.host or "").lower()
        expected_host = f"db.{self.test_supabase_project_ref}.supabase.co"
        if test_host != expected_host:
            raise ValueError("TEST_SUPABASE_PROJECT_REF 必须匹配测试 URL 的 project ref")

        deployment_value = os.environ.get("MIGRATION_DATABASE_URL")
        if deployment_value:
            try:
                deployment_url = make_url(deployment_value)
            except ArgumentError as error:
                raise ValueError("MIGRATION_DATABASE_URL 格式无效，无法确认测试库独立") from error
            if (deployment_url.host or "").lower() == test_host:
                raise ValueError("TEST_MIGRATION_DATABASE_URL 不得指向部署迁移库")
        return self
