"""Supabase Storage 私有对象存储边界。"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import httpx

from app.config import Settings
from app.parsing.models import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE

FILE_CHUNK_BYTES = 1024 * 1024


class SupabaseStorageError(RuntimeError):
    """Supabase Storage 请求失败；错误内容不得包含凭据或对象正文。"""


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
    ) -> None:
        self._client = client
        self._storage_url = storage_url.rstrip("/")
        self._secret_key = secret_key
        self._bucket_name = bucket_name
        self._signed_url_ttl_seconds = signed_url_ttl_seconds

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        client: httpx.AsyncClient,
    ) -> "SupabaseObjectStorage":
        """复用项目 Secret Key，不引入第二套对象存储凭据。"""

        return cls(
            client=client,
            storage_url=settings.supabase_storage_url,
            secret_key=settings.supabase_secret_key.get_secret_value(),
            bucket_name=settings.supabase_storage_bucket,
            signed_url_ttl_seconds=settings.supabase_storage_signed_url_ttl_seconds,
        )

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
        await self._require_success(
            "POST",
            self._object_url(key),
            headers=headers,
            content=content,
            error_message="规范文本写入失败",
        )

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
        expected_prefix = f"/object/sign/{bucket}/"
        if not isinstance(signed_path, str) or not signed_path.startswith(expected_prefix):
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
