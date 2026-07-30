"""阶段十二导出的安全 API 与 Worker 契约。"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.grading import canonical_sha256

ExportType = Literal["draft", "final"]
ExportStatus = Literal["queued", "running", "completed", "failed"]


class ExportCreateInput(BaseModel):
    """教师选择一个明确批次和导出类型。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grading_job_id: UUID
    export_type: ExportType

    def request_hash(self) -> bytes:
        return canonical_sha256(self)


class ExportView(BaseModel):
    """不泄露对象路径和文件哈希的教师安全投影。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    assignment_id: UUID
    grading_job_id: UUID
    assignment_title: str = Field(min_length=1, max_length=300)
    export_type: ExportType
    status: ExportStatus
    paper_count: int = Field(ge=1, le=100)
    source_counts: dict[str, int]
    safe_filename: str | None
    error_code: str | None
    snapshot_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class ExportCreation(BaseModel):
    """原子创建或幂等命中的结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    export: ExportView
    created: bool


class ExportDownload(BaseModel):
    """短时下载地址；过期后重新请求，不重新创建导出。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    download_url: str
    expires_in_seconds: int = Field(ge=30, le=300)
    filename: str = Field(min_length=1, max_length=255)


class FrozenExport(BaseModel):
    """Worker 只读取创建时冻结的数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    export_type: ExportType
    workbook_schema_version: str
    snapshot_at: datetime
    generation_started_at: datetime
    batch_snapshot: dict[str, object]
    items: tuple[dict[str, object], ...] = Field(min_length=1, max_length=100)


class ClaimedExport(BaseModel):
    """带领取令牌的不可变 Worker 输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    export: FrozenExport
    lease_token: UUID
