"""Supabase Storage 私有对象存储边界。"""

import asyncio
import base64
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx

from app.config import ExportWorkerSettings, Settings, WorkerSettings
from app.parsing.models import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE

FILE_CHUNK_BYTES = 1024 * 1024
MAX_PRIVATE_JSON_BYTES = 20 * 1024 * 1024
MAX_EXPORT_BYTES = 50 * 1024 * 1024


class SupabaseStorageError(RuntimeError):
    """Supabase Storage 请求失败；错误内容不得包含凭据或对象正文。"""


class SupabaseStorageTimeout(SupabaseStorageError):
    """Storage 超时；远端写入或删除结果可能未知。"""


class StorageQuotaGate(Protocol):
    """每次对象写入前后的数据库字节预留边界。"""

    async def reserve_storage_growth(
        self,
        *,
        operation_key: str,
        object_key: str,
        content_sha256: bytes,
        requested_bytes: int,
    ) -> object: ...

    async def commit_storage_growth(self, reservation_id: UUID) -> object: ...

    async def mark_storage_growth_uncertain(self, reservation_id: UUID) -> object: ...


@dataclass(frozen=True, slots=True)
class SubmissionObjectKeys:
    """服务端生成的一篇论文的两个私有对象路径。"""

    source: str
    extracted: str


def build_submission_object_keys(
    *,
    owner_id: UUID,
    assignment_id: UUID,
    submission_id: UUID,
    media_type: str,
) -> SubmissionObjectKeys:
    """对象路径只由可信 UUID 和服务器识别的格式组成。"""

    if media_type == PDF_MEDIA_TYPE:
        extension = "pdf"
    elif media_type == DOCX_MEDIA_TYPE:
        extension = "docx"
    else:
        raise ValueError("不支持的论文媒体类型")
    prefix = f"teachers/{owner_id}/assignments/{assignment_id}/submissions/{submission_id}"
    return SubmissionObjectKeys(
        source=f"{prefix}/source.{extension}",
        extracted=f"{prefix}/document-blocks.v1.json",
    )


async def stream_file(path: Path) -> AsyncIterator[bytes]:
    """在线程中分块读取临时文件，避免阻塞事件循环或一次读入内存。"""

    body = await asyncio.to_thread(path.open, "rb")
    try:
        while chunk := await asyncio.to_thread(body.read, FILE_CHUNK_BYTES):
            yield chunk
    finally:
        await asyncio.to_thread(body.close)


class SupabaseObjectStorage:
    """通过 Supabase Storage REST API 管理私有对象和短时读取地址。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        storage_url: str,
        secret_key: str,
        bucket_name: str,
        signed_url_ttl_seconds: int,
        quota: StorageQuotaGate | None = None,
    ) -> None:
        self._client = client
        self._storage_url = storage_url.rstrip("/")
        self._secret_key = secret_key
        self._bucket_name = bucket_name
        self._signed_url_ttl_seconds = signed_url_ttl_seconds
        self._quota = quota

    @classmethod
    def from_settings(
        cls,
        settings: Settings | WorkerSettings | ExportWorkerSettings,
        client: httpx.AsyncClient,
        *,
        quota: StorageQuotaGate | None = None,
    ) -> "SupabaseObjectStorage":
        """复用项目 Secret Key，不引入第二套对象存储凭据。"""

        return cls(
            client=client,
            storage_url=settings.supabase_storage_url,
            secret_key=settings.supabase_secret_key.get_secret_value(),
            bucket_name=settings.supabase_storage_bucket,
            signed_url_ttl_seconds=settings.supabase_storage_signed_url_ttl_seconds,
            quota=quota,
        )

    @staticmethod
    def _quota_operation_key(key: str, content_sha256: bytes) -> str:
        identity = hashlib.sha256(
            b"paper-grading:storage-growth:v1\0" + key.encode("utf-8") + b"\0" + content_sha256
        ).hexdigest()
        return f"storage:{identity}"

    @asynccontextmanager
    async def _reserve_growth(
        self,
        *,
        key: str,
        content_sha256: bytes,
        requested_bytes: int,
    ) -> AsyncIterator[None]:
        if self._quota is None:
            yield
            return
        result = await self._quota.reserve_storage_growth(
            operation_key=self._quota_operation_key(key, content_sha256),
            object_key=key,
            content_sha256=content_sha256,
            requested_bytes=requested_bytes,
        )
        reservation_id = getattr(result, "reservation_id", None)
        if reservation_id is not None and not isinstance(reservation_id, UUID):
            raise RuntimeError("Storage 配额预留标识无效")
        try:
            yield
        except BaseException as error:
            if reservation_id is not None:
                try:
                    await asyncio.shield(self._quota.mark_storage_growth_uncertain(reservation_id))
                except BaseException as finalize_error:
                    error.add_note("Storage 写入结果不确定且配额预留收口失败")
                    raise error from finalize_error
            raise
        else:
            if reservation_id is not None:
                await self._quota.commit_storage_growth(reservation_id)

    def _auth_headers(self) -> dict[str, str]:
        return {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
        }

    def _object_url(self, key: str) -> str:
        bucket = quote(self._bucket_name, safe="")
        object_path = quote(key, safe="/")
        return f"{self._storage_url}/object/{bucket}/{object_path}"

    async def _require_success(
        self,
        method: str,
        url: str,
        *,
        error_message: str,
        headers: dict[str, str] | None = None,
        content: bytes | AsyncIterator[bytes] | None = None,
        json_body: object | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                content=content,
                json=json_body,
            )
        except httpx.TimeoutException as error:
            raise SupabaseStorageTimeout(error_message) from error
        except (httpx.HTTPError, OSError) as error:
            raise SupabaseStorageError(error_message) from error
        if not response.is_success:
            raise SupabaseStorageError(error_message)
        return response

    async def put_file(
        self,
        key: str,
        path: Path,
        *,
        media_type: str,
        content_sha256: bytes,
    ) -> None:
        """分块写入论文原文件；确定性路径允许失败任务安全重试。"""

        metadata = base64.b64encode(
            json.dumps(
                {"sha256": content_sha256.hex()},
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii")
        try:
            content_length = path.stat().st_size
        except OSError as error:
            raise SupabaseStorageError("论文原文件写入失败") from error
        headers = {
            **self._auth_headers(),
            "Content-Type": media_type,
            "Content-Length": str(content_length),
            "Cache-Control": "max-age=0, no-store",
            "x-metadata": metadata,
            "x-upsert": "true",
        }
        async with self._reserve_growth(
            key=key,
            content_sha256=content_sha256,
            requested_bytes=content_length,
        ):
            await self._require_success(
                "POST",
                self._object_url(key),
                headers=headers,
                content=stream_file(path),
                error_message="论文原文件写入失败",
            )

    async def put_json(self, key: str, content: bytes) -> None:
        """写入版本化规范文本 JSON，并覆盖不确定失败留下的同路径对象。"""

        headers = {
            **self._auth_headers(),
            "Content-Type": "application/json",
            "Cache-Control": "max-age=0, no-store",
            "x-upsert": "true",
        }
        content_sha256 = hashlib.sha256(content).digest()
        async with self._reserve_growth(
            key=key,
            content_sha256=content_sha256,
            requested_bytes=len(content),
        ):
            await self._require_success(
                "POST",
                self._object_url(key),
                headers=headers,
                content=content,
                error_message="规范文本写入失败",
            )

    async def get_json(self, key: str) -> bytes:
        """使用服务端凭据读取有大小上限的私有 JSON 对象。"""

        response = await self._require_success(
            "GET",
            self._object_url(key),
            headers={**self._auth_headers(), "Accept": "application/json"},
            error_message="私有 JSON 读取失败",
        )
        content = response.content
        if len(content) > MAX_PRIVATE_JSON_BYTES:
            raise SupabaseStorageError("私有 JSON 超过安全上限")
        return content

    async def put_json_once(self, key: str, content: bytes) -> None:
        """只创建不可变审计对象；重放时必须与已有字节完全一致。"""

        if len(content) > MAX_PRIVATE_JSON_BYTES:
            raise SupabaseStorageError("评分审计对象超过安全上限")
        headers = {
            **self._auth_headers(),
            "Content-Type": "application/json",
            "Cache-Control": "max-age=0, no-store",
            "x-upsert": "false",
        }
        content_sha256 = hashlib.sha256(content).digest()
        async with self._reserve_growth(
            key=key,
            content_sha256=content_sha256,
            requested_bytes=len(content),
        ):
            try:
                response = await self._client.request(
                    "POST",
                    self._object_url(key),
                    headers=headers,
                    content=content,
                )
            except (httpx.HTTPError, OSError) as error:
                raise SupabaseStorageError("评分审计对象写入失败") from error
            if response.is_success:
                return
            if response.status_code not in {400, 409}:
                raise SupabaseStorageError("评分审计对象写入失败")
            existing = await self.get_json(key)
            if existing != content:
                raise SupabaseStorageError("评分审计对象已存在但内容不一致")

    async def put_file_once(
        self,
        key: str,
        path: Path,
        *,
        media_type: str,
        content_sha256: bytes,
    ) -> bool:
        """禁用覆盖；同路径同哈希可安全续接，返回是否本次创建。"""

        try:
            content_length = path.stat().st_size
        except OSError as error:
            raise SupabaseStorageError("导出文件读取失败") from error
        if not 0 < content_length <= MAX_EXPORT_BYTES or len(content_sha256) != 32:
            raise SupabaseStorageError("导出文件无效")
        metadata = base64.b64encode(
            json.dumps(
                {"sha256": content_sha256.hex()},
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii")
        headers = {
            **self._auth_headers(),
            "Content-Type": media_type,
            "Content-Length": str(content_length),
            "Cache-Control": "max-age=0, no-store",
            "x-metadata": metadata,
            "x-upsert": "false",
        }
        async with self._reserve_growth(
            key=key,
            content_sha256=content_sha256,
            requested_bytes=content_length,
        ):
            try:
                response = await self._client.request(
                    "POST",
                    self._object_url(key),
                    headers=headers,
                    content=stream_file(path),
                )
            except (httpx.HTTPError, OSError) as error:
                raise SupabaseStorageError("导出文件写入失败") from error
            if response.is_success:
                return True
            if response.status_code not in {400, 409}:
                raise SupabaseStorageError("导出文件写入失败")
            existing = await self._require_success(
                "GET",
                self._object_url(key),
                headers=self._auth_headers(),
                error_message="导出文件写入失败",
            )
            if (
                len(existing.content) > MAX_EXPORT_BYTES
                or hashlib.sha256(existing.content).digest() != content_sha256
            ):
                raise SupabaseStorageError("导出对象已存在但内容不一致")
            return False

    async def delete_if_sha256(self, key: str, expected_sha256: bytes) -> bool:
        """仅删除内容哈希仍等于本次上传结果的精确对象。"""

        if len(expected_sha256) != 32:
            return False
        response = await self._require_success(
            "GET",
            self._object_url(key),
            headers=self._auth_headers(),
            error_message="导出补偿校验失败",
        )
        content = response.content
        if len(content) > MAX_EXPORT_BYTES or hashlib.sha256(content).digest() != expected_sha256:
            return False
        await self.delete(key)
        return True

    async def delete(self, key: str) -> None:
        """补偿删除尚未被数据库提交引用的对象。"""

        bucket = quote(self._bucket_name, safe="")
        await self._require_success(
            "DELETE",
            f"{self._storage_url}/object/{bucket}",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            json_body={"prefixes": [key]},
            error_message="对象补偿删除失败",
        )

    async def delete_with_result(self, key: str) -> Literal["deleted", "missing"]:
        """保留清理删除一个对象，并依据 Storage 返回数组区分不存在。"""

        bucket = quote(self._bucket_name, safe="")
        response = await self._require_success(
            "DELETE",
            f"{self._storage_url}/object/{bucket}",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            json_body={"prefixes": [key]},
            error_message="保留对象删除失败",
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise SupabaseStorageError("保留对象删除结果无效") from error
        if not isinstance(payload, list):
            raise SupabaseStorageError("保留对象删除结果无效")
        if not payload:
            return "missing"
        for item in payload:
            if isinstance(item, dict) and item.get("name") == key:
                return "deleted"
        raise SupabaseStorageError("保留对象删除结果无效")

    async def create_download_url(self, key: str) -> str:
        """只为数据库已完成归属检查的对象生成短时 URL。"""

        bucket = quote(self._bucket_name, safe="")
        object_path = quote(key, safe="/")
        response = await self._require_success(
            "POST",
            f"{self._storage_url}/object/sign/{bucket}/{object_path}",
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            json_body={"expiresIn": self._signed_url_ttl_seconds},
            error_message="短时读取地址生成失败",
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise SupabaseStorageError("Supabase Storage 返回了无效读取地址") from error
        signed_path = payload.get("signedURL") if isinstance(payload, dict) else None
        expected_path = f"/object/sign/{bucket}/{object_path}"
        if not isinstance(signed_path, str):
            raise SupabaseStorageError("Supabase Storage 返回了无效读取地址")
        parsed = urlsplit(signed_path)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.path != expected_path
            or not parsed.query
            or parsed.fragment
        ):
            raise SupabaseStorageError("Supabase Storage 返回了无效读取地址")
        return f"{self._storage_url}{signed_path}"

    async def require_private_bucket(
        self,
        *,
        expected_file_size_limit_bytes: int | None = None,
        expected_allowed_mime_types: set[str] | None = None,
    ) -> None:
        """真实验收时确认目标桶存在、未公开且限制符合阶段配置。"""

        bucket = quote(self._bucket_name, safe="")
        response = await self._require_success(
            "GET",
            f"{self._storage_url}/bucket/{bucket}",
            headers=self._auth_headers(),
            error_message="私有桶配置检查失败",
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise SupabaseStorageError("私有桶配置检查失败") from error
        if not isinstance(payload, dict) or payload.get("public") is not False:
            raise SupabaseStorageError("Supabase Storage 桶必须保持私有")
        if (
            expected_file_size_limit_bytes is not None
            and payload.get("file_size_limit") != expected_file_size_limit_bytes
        ):
            raise SupabaseStorageError("Supabase Storage 桶文件大小限制不符合阶段配置")
        if expected_allowed_mime_types is not None:
            allowed_mime_types = payload.get("allowed_mime_types")
            if (
                not isinstance(allowed_mime_types, list)
                or not all(isinstance(media_type, str) for media_type in allowed_mime_types)
                or set(allowed_mime_types) != expected_allowed_mime_types
            ):
                raise SupabaseStorageError("Supabase Storage 桶 MIME 限制不符合阶段配置")
