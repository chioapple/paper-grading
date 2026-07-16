"""阶段七论文上传 API 与内部持久化契约。"""

from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.parsing.models import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE

SubmissionStatus = Literal["uploaded", "parsing", "ready", "failed"]
SubmissionMediaType = Literal[
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]
ReservationState = Literal[
    "created",
    "duplicate",
    "assignment_not_found",
    "assignment_not_ready",
]


@dataclass(frozen=True, slots=True)
class IncomingSubmission:
    """FastAPI 上传对象收窄后的同步文件流。"""

    stream: BinaryIO
    original_filename: str
    client_media_type: str | None


@dataclass(frozen=True, slots=True)
class SubmissionReservationRequest:
    """短事务预留论文行所需的可信元数据。"""

    id: UUID
    assignment_id: UUID
    original_filename: str
    media_type: SubmissionMediaType
    file_size_bytes: int
    content_sha256: bytes
    source_object_key: str


class SubmissionView(BaseModel):
    """教师可见的论文元数据；不暴露哈希或 Storage 对象路径。"""

    model_config = ConfigDict(frozen=True)

    id: UUID
    assignment_id: UUID
    original_filename: str
    media_type: SubmissionMediaType
    file_size_bytes: int
    status: SubmissionStatus
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SubmissionReservation:
    """预留结果明确区分重复文件和作业状态。"""

    state: ReservationState
    submission: SubmissionView | None


class SubmissionUploadResult(BaseModel):
    """单文件上传结果；前端批量动作按输入位置自行关联。"""

    model_config = ConfigDict(frozen=True)

    duplicate: bool
    submission: SubmissionView


class SubmissionDownload(BaseModel):
    """经过教师归属检查后的短时读取地址。"""

    model_config = ConfigDict(frozen=True)

    url: str
    expires_in_seconds: int


def media_type_literal(value: str) -> SubmissionMediaType:
    """将解析器已验证的媒体类型收窄为持久化字面量。"""

    if value == PDF_MEDIA_TYPE:
        return PDF_MEDIA_TYPE
    if value == DOCX_MEDIA_TYPE:
        return DOCX_MEDIA_TYPE
    raise ValueError("不支持的论文媒体类型")
