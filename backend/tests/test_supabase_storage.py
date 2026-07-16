"""阶段七 Supabase Storage 私有对象存储测试。"""

import asyncio
import base64
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.parsing.models import PDF_MEDIA_TYPE
from app.storage.supabase import (
    SupabaseObjectStorage,
    SupabaseStorageError,
    build_submission_object_keys,
)

OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
ASSIGNMENT_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("77777777-7777-7777-7777-777777777777")
SECRET_KEY = "sb_secret_test"


def test_supabase_storage_uses_server_keys_streaming_upsert_and_signed_urls(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    keys = build_submission_object_keys(
        owner_id=OWNER_ID,
        assignment_id=ASSIGNMENT_ID,
        submission_id=SUBMISSION_ID,
        media_type=PDF_MEDIA_TYPE,
    )
    requests: list[tuple[str, str, httpx.Headers, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        requests.append((request.method, str(request.url), request.headers, body))
        if "/object/sign/" in request.url.path:
            return httpx.Response(
                200,
                json={"signedURL": f"/object/sign/paper-grading-test/{keys.source}?token=test"},
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "public": False,
                    "file_size_limit": 20 * 1024 * 1024,
                    "allowed_mime_types": [
                        PDF_MEDIA_TYPE,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "application/json",
                    ],
                },
            )
        return httpx.Response(200, json={})

    async def scenario() -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.put_file(
                keys.source,
                source,
                media_type=PDF_MEDIA_TYPE,
                content_sha256=bytes.fromhex("00" * 32),
            )
            await storage.put_json(
                keys.extracted,
                b'{"schema_version":"document-blocks.v1"}',
            )
            url = await storage.create_download_url(keys.source)
            await storage.require_private_bucket(
                expected_file_size_limit_bytes=20 * 1024 * 1024,
                expected_allowed_mime_types={
                    PDF_MEDIA_TYPE,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/json",
                },
            )
            await storage.delete(keys.source)
            return url

    url = asyncio.run(scenario())

    assert keys.source == (
        "teachers/22222222-2222-2222-2222-222222222222/"
        "assignments/44444444-4444-4444-4444-444444444444/"
        "submissions/77777777-7777-7777-7777-777777777777/source.pdf"
    )
    assert keys.extracted.endswith("/document-blocks.v1.json")
    source_headers = requests[0][2]
    assert requests[0][3] == b"%PDF-test"
    assert source_headers["authorization"] == f"Bearer {SECRET_KEY}"
    assert source_headers["apikey"] == SECRET_KEY
    assert source_headers["x-upsert"] == "true"
    assert source_headers["content-length"] == str(len(b"%PDF-test"))
    metadata = json.loads(base64.b64decode(source_headers["x-metadata"]))
    assert metadata == {"sha256": "00" * 32}
    assert requests[1][2]["content-type"] == "application/json"
    assert json.loads(requests[2][3]) == {"expiresIn": 60}
    assert requests[3][0] == "GET"
    assert requests[4][0] == "DELETE"
    assert json.loads(requests[4][3]) == {"prefixes": [keys.source]}
    assert url == (
        "https://test-project.supabase.co/storage/v1/object/sign/"
        f"paper-grading-test/{keys.source}?token=test"
    )


def test_supabase_storage_hides_remote_error_details() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="remote detail must not escape")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.put_json("test.json", b"{}")

    with pytest.raises(SupabaseStorageError, match="规范文本写入失败") as error:
        asyncio.run(scenario())

    assert "remote detail" not in str(error.value)


def test_supabase_storage_rejects_malformed_signed_url_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"signedURL": "https://attacker.example/object"})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.create_download_url("teachers/test/source.pdf")

    with pytest.raises(SupabaseStorageError, match="无效读取地址"):
        asyncio.run(scenario())


def test_supabase_storage_rejects_misconfigured_private_bucket() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "public": False,
                "file_size_limit": 10 * 1024 * 1024,
                "allowed_mime_types": [PDF_MEDIA_TYPE, "application/json"],
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.require_private_bucket(
                expected_file_size_limit_bytes=20 * 1024 * 1024,
                expected_allowed_mime_types={PDF_MEDIA_TYPE, "application/json"},
            )

    with pytest.raises(SupabaseStorageError, match="文件大小限制"):
        asyncio.run(scenario())
