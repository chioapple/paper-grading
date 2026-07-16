"""阶段七教师论文上传、列表和短时下载接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile

from app.auth.dependencies import require_teacher
from app.auth.models import CurrentAccount
from app.submissions.dependencies import get_submission_service
from app.submissions.models import (
    IncomingSubmission,
    SubmissionDownload,
    SubmissionUploadResult,
    SubmissionView,
)
from app.submissions.service import SubmissionService

router = APIRouter(prefix="/assignments/{assignment_id}/submissions", tags=["submissions"])


@router.post("", response_model=SubmissionUploadResult)
async def upload_submission(
    assignment_id: UUID,
    file: Annotated[UploadFile, File()],
    service: Annotated[SubmissionService, Depends(get_submission_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> SubmissionUploadResult:
    """单文件流式上传；前端一次最多选择 100 篇并逐文件调用。"""

    try:
        return await service.upload_submission(
            teacher.id,
            assignment_id,
            IncomingSubmission(
                stream=file.file,
                original_filename=file.filename or "",
                client_media_type=file.content_type,
            ),
        )
    finally:
        await file.close()


@router.get("", response_model=list[SubmissionView])
async def list_submissions(
    assignment_id: UUID,
    service: Annotated[SubmissionService, Depends(get_submission_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> list[SubmissionView]:
    """列出当前教师在目标作业下的全部论文状态。"""

    return await service.list_submissions(teacher.id, assignment_id)


@router.post("/{submission_id}/download", response_model=SubmissionDownload)
async def create_submission_download(
    assignment_id: UUID,
    submission_id: UUID,
    service: Annotated[SubmissionService, Depends(get_submission_service)],
    teacher: Annotated[CurrentAccount, Depends(require_teacher)],
) -> SubmissionDownload:
    """归属检查通过后才生成短时 Supabase Storage 读取地址。"""

    return await service.create_download(teacher.id, assignment_id, submission_id)
