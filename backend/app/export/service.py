"""导出创建、查询和短时下载的业务边界。"""

from typing import Protocol
from uuid import UUID

from app.export.models import ExportCreateInput, ExportCreation, ExportDownload, ExportView


class ExportNotFoundError(RuntimeError):
    """资源不存在或不属于当前教师。"""


class ExportStateError(RuntimeError):
    """批次或导出状态不允许当前操作。"""


class ExportIdempotencyConflict(RuntimeError):
    """同一幂等键被用于不同请求。"""


class ExportDataError(RuntimeError):
    """冻结来源不满足严格导出契约。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ExportRepository(Protocol):
    async def create(
        self,
        owner_id: UUID,
        request: ExportCreateInput,
        idempotency_key: str,
    ) -> ExportCreation: ...

    async def list(self, owner_id: UUID) -> tuple[ExportView, ...]: ...

    async def get(self, owner_id: UUID, export_id: UUID) -> ExportView | None: ...

    async def get_object_key(self, owner_id: UUID, export_id: UUID) -> str | None: ...


class ExportQueue(Protocol):
    async def enqueue(self, export_id: UUID) -> None: ...


class ExportDownloadStorage(Protocol):
    async def create_download_url(self, key: str) -> str: ...


class ExportService:
    """保持 HTTP 请求短小，Excel 生成只在独立 Worker 中执行。"""

    def __init__(
        self,
        *,
        repository: ExportRepository,
        queue: ExportQueue,
        storage: ExportDownloadStorage,
        signed_url_ttl_seconds: int,
    ) -> None:
        self._repository = repository
        self._queue = queue
        self._storage = storage
        self._signed_url_ttl_seconds = signed_url_ttl_seconds

    async def create(
        self,
        owner_id: UUID,
        request: ExportCreateInput,
        idempotency_key: str,
    ) -> ExportCreation:
        key = idempotency_key.strip()
        if not key or len(key) > 200:
            raise ExportDataError("invalid_idempotency_key", "幂等键无效")
        creation = await self._repository.create(owner_id, request, key)
        if creation.export.status == "queued":
            await self._queue.enqueue(creation.export.id)
        return creation

    async def list(self, owner_id: UUID) -> tuple[ExportView, ...]:
        return await self._repository.list(owner_id)

    async def get(self, owner_id: UUID, export_id: UUID) -> ExportView:
        export = await self._repository.get(owner_id, export_id)
        if export is None:
            raise ExportNotFoundError
        return export

    async def download(self, owner_id: UUID, export_id: UUID) -> ExportDownload:
        export = await self.get(owner_id, export_id)
        if export.status != "completed" or export.safe_filename is None:
            raise ExportStateError("导出尚未完成")
        object_key = await self._repository.get_object_key(owner_id, export_id)
        if object_key is None:
            raise ExportNotFoundError
        return ExportDownload(
            download_url=await self._storage.create_download_url(object_key),
            expires_in_seconds=self._signed_url_ttl_seconds,
            filename=export.safe_filename,
        )
