"""阶段七真实 Supabase Storage 私有桶和短时签名 URL 验收。"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl, quote, urlencode, urlsplit
from uuid import uuid4

import httpx

from app.config import Settings
from app.parsing.models import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE
from app.storage.supabase import SupabaseObjectStorage

STAGE7_FILE_SIZE_LIMIT_BYTES = 20 * 1024 * 1024
STAGE7_ALLOWED_MIME_TYPES = {PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE, "application/json"}


def require_access_rejected(response: httpx.Response, *, label: str) -> None:
    """安全负向检查必须由结构化认证或权限错误拒绝。"""

    if response.status_code not in {400, 401, 403}:
        raise RuntimeError(f"Supabase Storage {label}失败，返回 {response.status_code}")
    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(f"Supabase Storage {label}失败，拒绝响应不是 JSON") from error
    if not isinstance(payload, dict) or not any(
        isinstance(payload.get(field), str) and payload[field]
        for field in ("statusCode", "code", "error", "message")
    ):
        raise RuntimeError(f"Supabase Storage {label}失败，拒绝响应缺少错误标识")


def tamper_signed_url_token(signed_url: str) -> str:
    """只修改签名 token，保留已签名资源路径。"""

    parsed = urlsplit(signed_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    token = query.get("token")
    if not token:
        raise RuntimeError("Supabase Storage 签名地址缺少 token")
    segments = token.split(".")
    if len(segments) != 3 or not segments[2]:
        raise RuntimeError("Supabase Storage 签名 token 格式无效")
    signature = segments[2]
    index = len(signature) // 2
    replacement = "a" if signature[index] != "a" else "b"
    segments[2] = f"{signature[:index]}{replacement}{signature[index + 1 :]}"
    query["token"] = ".".join(segments)
    return parsed._replace(query=urlencode(query)).geturl()


async def verify() -> None:
    """写入无敏感信息的临时对象，验证私有读取、签名读取和过期拒绝。"""

    settings = Settings.load()
    object_key = f"acceptance/stage7/{uuid4()}.json"
    content = json.dumps({"purpose": "stage7-supabase-storage-acceptance"}).encode("utf-8")
    bucket = quote(settings.supabase_storage_bucket, safe="")
    object_path = quote(object_key, safe="/")
    unsigned_url = f"{settings.supabase_storage_url}/object/public/{bucket}/{object_path}"

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=settings.supabase_storage_timeout_seconds,
        trust_env=False,
    ) as client:
        storage = SupabaseObjectStorage.from_settings(settings, client)
        await storage.require_private_bucket(
            expected_file_size_limit_bytes=STAGE7_FILE_SIZE_LIMIT_BYTES,
            expected_allowed_mime_types=STAGE7_ALLOWED_MIME_TYPES,
        )
        await storage.put_json(object_key, content)
        try:
            unsigned = await client.get(unsigned_url)
            require_access_rejected(unsigned, label="私有读取检查")

            signed_url = await storage.create_download_url(object_key)
            signed = await client.get(signed_url)
            if signed.status_code != 200 or signed.content != content:
                raise RuntimeError(f"Supabase Storage 签名读取检查失败，返回 {signed.status_code}")

            tampered = await client.get(tamper_signed_url_token(signed_url))
            require_access_rejected(tampered, label="篡改签名检查")

            await asyncio.sleep(settings.supabase_storage_signed_url_ttl_seconds + 2)
            expired = await client.get(signed_url)
            require_access_rejected(expired, label="过期签名检查")
        finally:
            await storage.delete(object_key)

    print("stage7 Supabase Storage acceptance passed")


if __name__ == "__main__":
    asyncio.run(verify())
