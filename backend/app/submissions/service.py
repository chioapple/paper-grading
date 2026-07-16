"""论文上传、解析、存储和状态转换用例。"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from uuid import UUID, uuid4

from app.parsing.models import DocumentParseError, ParseLimits
from app.parsing.normalize import parse_document, stage_upload_file
from app.storage.supabase import (
    SubmissionObjectKeys,
    SupabaseStorageError,
    build_submission_object_keys,
)
from app.submissions.models import (
    IncomingSubmission,
    SubmissionDownload,
    SubmissionReservation,
    SubmissionReservationRequest,
    SubmissionUploadResult,
    SubmissionView,
    media_type_literal,
)


class SubmissionAssignmentNotFoundError(LookupError):
    """当前教师名下不存在目标作业。"""


class SubmissionAssignmentStateError(RuntimeError):
    """只有已确认 Rubric 的 ready 作业可以接收论文。"""


class SubmissionTransitionError(RuntimeError):
    """数据库中的论文状态已被并发修改或迁移未就绪。"""


class SubmissionNotFoundError(LookupError):
    """当前教师名下不存在目标论文。"""


class SubmissionRepository(Protocol):
    """论文元数据与最小权限状态转换边界。"""

    async def reserve_submission(
        self,
        owner_id: UUID,
        request: SubmissionReservationRequest,
    ) -> SubmissionReservation: ...

    async def transition_submission(
        self,
        owner_id: UUID,
        submission_id: UUID,
        *,
        status: str,
        extracted_object_key: str | None = None,
        error_code: str | None = None,
    ) -> SubmissionView | None: ...

    async def list_submissions(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> list[SubmissionView] | None: ...

    async def get_ready_source_key(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        submission_id: UUID,
    ) -> str | None: ...


class SubmissionObjectStorage(Protocol):
    """服务层使用的私有对象存储最小接口。"""

    async def put_file(
        self,
        key: str,
        path: Path,
        *,
        media_type: str,
        content_sha256: bytes,
    ) -> None: ...

    async def put_json(self, key: str, content: bytes) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def create_download_url(self, key: str) -> str: ...


class SubmissionService:
    """单文件流式处理；浏览器最多选择 100 篇并逐文件调用。"""

    def __init__(
        self,
        *,
        repository: SubmissionRepository,
        storage: SubmissionObjectStorage,
        parse_limits: ParseLimits | None = None,
        temporary_root: Path | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        signed_url_ttl_seconds: int = 60,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._parse_limits = parse_limits or ParseLimits()
        self._temporary_root = temporary_root
        self._id_factory = id_factory
        self._signed_url_ttl_seconds = signed_url_ttl_seconds

    async def _transition_or_raise(
        self,
        owner_id: UUID,
        submission_id: UUID,
        *,
        status: str,
        extracted_object_key: str | None = None,
        error_code: str | None = None,
    ) -> SubmissionView:
        transitioned = await self._repository.transition_submission(
            owner_id,
            submission_id,
            status=status,
            extracted_object_key=extracted_object_key,
            error_code=error_code,
        )
        if transitioned is None:
            raise SubmissionTransitionError("论文状态转换失败")
        return transitioned

    async def _mark_failed(
        self,
        owner_id: UUID,
        submission_id: UUID,
        error_code: str,
    ) -> None:
        await self._transition_or_raise(
            owner_id,
            submission_id,
            status="failed",
            error_code=error_code,
        )

    async def _put_extracted_object(self, key: str, content: bytes) -> None:
        """任务取消时先等待远端写入结束，让后续补偿删除没有竞态。"""

        write_task = asyncio.create_task(self._storage.put_json(key, content))
        try:
            await asyncio.shield(write_task)
        except asyncio.CancelledError:
            with suppress(Exception):
                await write_task
            raise

    async def _delete_after_failure(self, key: str, primary_error: BaseException) -> None:
        """补偿失败时仍保留原始业务异常类型，并挂接清理异常供排查。"""

        try:
            await self._storage.delete(key)
        except Exception as cleanup_error:
            primary_error.add_note("未引用的规范文本对象补偿删除失败")
            raise primary_error from cleanup_error

    async def _mark_cancelled(
        self,
        owner_id: UUID,
        submission_id: UUID,
        cancellation: asyncio.CancelledError,
    ) -> None:
        """取消请求必须落为可重试失败，不能永久停在 uploaded/parsing。"""

        try:
            await self._mark_failed(owner_id, submission_id, "processing_cancelled")
        except Exception as status_error:
            cancellation.add_note("取消后写入失败状态未成功")
            raise cancellation from status_error

    async def upload_submission(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        incoming: IncomingSubmission,
    ) -> SubmissionUploadResult:
        """预留后在事务外完成对象写入与同步解析。"""

        with TemporaryDirectory(prefix="paper-grading-", dir=self._temporary_root) as directory:
            staged = await asyncio.to_thread(
                stage_upload_file,
                incoming.stream,
                original_filename=incoming.original_filename,
                client_media_type=incoming.client_media_type,
                temporary_directory=Path(directory),
                limits=self._parse_limits,
            )
            try:
                submission_id = self._id_factory()
                keys = build_submission_object_keys(
                    owner_id=owner_id,
                    assignment_id=assignment_id,
                    submission_id=submission_id,
                    media_type=staged.media_type,
                )
                reservation = await self._repository.reserve_submission(
                    owner_id,
                    SubmissionReservationRequest(
                        id=submission_id,
                        assignment_id=assignment_id,
                        original_filename=staged.original_filename,
                        media_type=media_type_literal(staged.media_type),
                        file_size_bytes=staged.size_bytes,
                        content_sha256=staged.content_sha256,
                        source_object_key=keys.source,
                    ),
                )
                submission, keys, duplicate = await self._resolve_reservation(
                    owner_id,
                    assignment_id,
                    reservation,
                    staged.media_type,
                )
                if duplicate:
                    return SubmissionUploadResult(duplicate=True, submission=submission)

                try:
                    try:
                        await self._storage.put_file(
                            keys.source,
                            staged.path,
                            media_type=staged.media_type,
                            content_sha256=staged.content_sha256,
                        )
                    except SupabaseStorageError:
                        await self._mark_failed(owner_id, submission.id, "storage_source_failed")
                        raise

                    await self._transition_or_raise(owner_id, submission.id, status="parsing")
                    try:
                        parsed = await asyncio.to_thread(
                            parse_document,
                            staged,
                            self._parse_limits,
                        )
                    except DocumentParseError as error:
                        await self._mark_failed(owner_id, submission.id, error.code)
                        raise

                    try:
                        try:
                            await self._put_extracted_object(
                                keys.extracted,
                                parsed.model_dump_json().encode("utf-8"),
                            )
                        except SupabaseStorageError:
                            await self._mark_failed(
                                owner_id,
                                submission.id,
                                "storage_extracted_failed",
                            )
                            raise
                        ready = await self._transition_or_raise(
                            owner_id,
                            submission.id,
                            status="ready",
                            extracted_object_key=keys.extracted,
                        )
                        return SubmissionUploadResult(duplicate=False, submission=ready)
                    except BaseException as error:
                        await self._delete_after_failure(keys.extracted, error)
                        raise
                except asyncio.CancelledError as cancellation:
                    await self._mark_cancelled(owner_id, submission.id, cancellation)
                    raise
            finally:
                staged.path.unlink(missing_ok=True)

    async def _resolve_reservation(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        reservation: SubmissionReservation,
        media_type: str,
    ) -> tuple[SubmissionView, SubmissionObjectKeys, bool]:
        if reservation.state == "assignment_not_found":
            raise SubmissionAssignmentNotFoundError("作业不存在")
        if reservation.state == "assignment_not_ready":
            raise SubmissionAssignmentStateError("作业尚未确认评分标准")
        submission = reservation.submission
        if submission is None:
            raise SubmissionTransitionError("论文预留结果不完整")
        keys = build_submission_object_keys(
            owner_id=owner_id,
            assignment_id=assignment_id,
            submission_id=submission.id,
            media_type=media_type,
        )
        if reservation.state == "created":
            return submission, keys, False
        if submission.status != "failed":
            return submission, keys, True
        reset = await self._transition_or_raise(owner_id, submission.id, status="uploaded")
        return reset, keys, False

    async def list_submissions(
        self,
        owner_id: UUID,
        assignment_id: UUID,
    ) -> list[SubmissionView]:
        submissions = await self._repository.list_submissions(owner_id, assignment_id)
        if submissions is None:
            raise SubmissionAssignmentNotFoundError("作业不存在")
        return submissions

    async def create_download(
        self,
        owner_id: UUID,
        assignment_id: UUID,
        submission_id: UUID,
    ) -> SubmissionDownload:
        key = await self._repository.get_ready_source_key(
            owner_id,
            assignment_id,
            submission_id,
        )
        if key is None:
            raise SubmissionNotFoundError("论文不存在或尚未解析完成")
        url = await self._storage.create_download_url(key)
        return SubmissionDownload(
            url=url,
            expires_in_seconds=self._signed_url_ttl_seconds,
        )
