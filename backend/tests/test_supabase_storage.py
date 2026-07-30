"""阶段七 Supabase Storage 私有对象存储测试。"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.monitoring.repository import QuotaExceededError, QuotaGateResult
from app.parsing.models import PDF_MEDIA_TYPE
from app.storage.supabase import (
    SupabaseObjectStorage,
    SupabaseStorageError,
    build_submission_object_keys,
)

OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
ASSIGNMENT_ID = UUID("44444444-4444-4444-4444-444444444444")
SUBMISSION_ID = UUID("77777777-7777-7777-7777-777777777777")
SECRET_KEY = "sb_secret_test"  # pragma: allowlist secret
QUOTA_RESERVATION_ID = UUID("88888888-8888-4888-8888-888888888888")


class RecordingStorageQuota:
    def __init__(self) -> None:
        self.reservations: list[tuple[str, str, bytes, int]] = []
        self.committed: list[UUID] = []
        self.released: list[UUID] = []
        self.uncertain: list[UUID] = []

    async def reserve_storage_growth(
        self,
        *,
        operation_key: str,
        object_key: str,
        content_sha256: bytes,
        requested_bytes: int,
    ) -> QuotaGateResult:
        self.reservations.append((operation_key, object_key, content_sha256, requested_bytes))
        return QuotaGateResult(
            state="ok",
            resource="storage",
            reservation_id=QUOTA_RESERVATION_ID,
            used_bytes=10,
            reserved_bytes=0,
            requested_bytes=requested_bytes,
            capacity_bytes=1_000,
        )

    async def commit_storage_growth(self, reservation_id: UUID) -> QuotaGateResult:
        self.committed.append(reservation_id)
        return self._finalized(reservation_id)

    async def release_storage_growth(self, reservation_id: UUID) -> QuotaGateResult:
        self.released.append(reservation_id)
        return self._finalized(reservation_id)

    async def mark_storage_growth_uncertain(
        self,
        reservation_id: UUID,
    ) -> QuotaGateResult:
        self.uncertain.append(reservation_id)
        return self._finalized(reservation_id)

    @staticmethod
    def _finalized(reservation_id: UUID) -> QuotaGateResult:
        return QuotaGateResult(
            state="ok",
            resource="storage",
            reservation_id=reservation_id,
            used_bytes=10,
            reserved_bytes=0,
            requested_bytes=2,
            capacity_bytes=1_000,
        )


def test_storage_write_reserves_exact_bytes_and_commits_after_remote_success() -> None:
    quota = RecordingStorageQuota()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
                quota=quota,
            )
            await storage.put_json("teachers/test/document.json", b"{}")

    asyncio.run(scenario())

    operation_key, object_key, content_sha256, requested_bytes = quota.reservations[0]
    assert operation_key.startswith("storage:")
    assert object_key == "teachers/test/document.json"
    assert content_sha256 == hashlib.sha256(b"{}").digest()
    assert requested_bytes == 2
    assert quota.committed == [QUOTA_RESERVATION_ID]
    assert quota.released == []
    assert quota.uncertain == []


def test_storage_quota_block_stops_before_the_remote_write() -> None:
    class BlockingStorageQuota(RecordingStorageQuota):
        async def reserve_storage_growth(
            self,
            *,
            operation_key: str,
            object_key: str,
            content_sha256: bytes,
            requested_bytes: int,
        ) -> QuotaGateResult:
            raise QuotaExceededError(
                resource="storage",
                code="storage_quota_exceeded",
            )

    remote_called = False

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal remote_called
        remote_called = True
        return httpx.Response(200, json={})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
                quota=BlockingStorageQuota(),
            )
            await storage.put_json("teachers/test/document.json", b"{}")

    with pytest.raises(QuotaExceededError, match="storage_quota_exceeded"):
        asyncio.run(scenario())

    assert remote_called is False


def test_storage_write_keeps_reservation_uncertain_when_remote_result_is_unknown() -> None:
    quota = RecordingStorageQuota()

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("remote result unknown", request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
                quota=quota,
            )
            await storage.put_json("teachers/test/document.json", b"{}")

    with pytest.raises(SupabaseStorageError, match="规范文本写入失败"):
        asyncio.run(scenario())

    assert quota.committed == []
    assert quota.released == []
    assert quota.uncertain == [QUOTA_RESERVATION_ID]


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


def test_grading_worker_reads_private_json_and_writes_audit_objects_once() -> None:
    key = "teachers/owner/grading-jobs/job/items/item/attempts/attempt/provider-response.v1.json"
    content = b'{"schema_version":"provider-response.v1"}'
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={})

    async def scenario() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.put_json_once(key, content)
            return await storage.get_json(key)

    loaded = asyncio.run(scenario())

    assert loaded == content
    assert requests[0].headers["x-upsert"] == "false"
    assert requests[0].headers["authorization"] == f"Bearer {SECRET_KEY}"
    assert requests[1].method == "GET"


def test_export_upload_disables_overwrite_and_compensation_checks_hash(tmp_path: Path) -> None:
    content = b"xlsx-bytes"
    file_hash = hashlib.sha256(content).digest()
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(content)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, content=content)
        return httpx.Response(200, json={})

    async def scenario() -> tuple[bool, bool]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            created = await storage.put_file_once(
                "exports/id/workbook.xlsx",
                path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                content_sha256=file_hash,
            )
            deleted = await storage.delete_if_sha256("exports/id/workbook.xlsx", file_hash)
            return created, deleted

    assert asyncio.run(scenario()) == (True, True)
    assert requests[0].headers["x-upsert"] == "false"
    assert requests[1].method == "GET"
    assert requests[2].method == "DELETE"


def test_export_upload_reuses_an_existing_object_only_when_bytes_match(tmp_path: Path) -> None:
    content = b"same-xlsx-bytes"
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(content)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, json={})
        return httpx.Response(200, content=content)

    async def scenario() -> bool:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            return await storage.put_file_once(
                "exports/id/workbook.xlsx",
                path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                content_sha256=hashlib.sha256(content).digest(),
            )

    assert asyncio.run(scenario()) is False


def test_export_upload_rejects_an_existing_object_with_different_bytes(tmp_path: Path) -> None:
    content = b"expected-xlsx-bytes"
    path = tmp_path / "workbook.xlsx"
    path.write_bytes(content)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, json={})
        return httpx.Response(200, content=b"different-xlsx-bytes")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.put_file_once(
                "exports/id/workbook.xlsx",
                path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                content_sha256=hashlib.sha256(content).digest(),
            )

    with pytest.raises(SupabaseStorageError, match="内容不一致"):
        asyncio.run(scenario())


def test_export_compensation_never_deletes_an_object_with_a_different_hash() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"other-owner-bytes")

    async def scenario() -> bool:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            return await storage.delete_if_sha256(
                "exports/id/workbook.xlsx",
                hashlib.sha256(b"expected-bytes").digest(),
            )

    assert asyncio.run(scenario()) is False
    assert [request.method for request in requests] == ["GET"]


def test_retention_delete_distinguishes_deleted_and_missing_objects() -> None:
    responses = [
        httpx.Response(200, json=[{"name": "teachers/owner/source.pdf"}]),
        httpx.Response(200, json=[]),
    ]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    async def scenario() -> tuple[str, str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            deleted = await storage.delete_with_result("teachers/owner/source.pdf")
            missing = await storage.delete_with_result("teachers/owner/source.pdf")
            return deleted, missing

    assert asyncio.run(scenario()) == ("deleted", "missing")


def test_retention_delete_rejects_an_ambiguous_storage_response() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.delete_with_result("teachers/owner/source.pdf")

    with pytest.raises(SupabaseStorageError, match="结果无效"):
        asyncio.run(scenario())


def test_grading_audit_object_conflict_must_match_the_existing_bytes() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(409, json={})
        return httpx.Response(200, content=b'{"different":true}')

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key=SECRET_KEY,
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await storage.put_json_once("attempt.json", b'{"expected":true}')

    with pytest.raises(SupabaseStorageError, match="已存在但内容不一致"):
        asyncio.run(scenario())


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


@pytest.mark.parametrize(
    "signed_url",
    [
        "/object/sign/paper-grading-test/teachers/other/source.pdf?token=test",
        "/object/sign/paper-grading-test/teachers/test/source.pdf/../other.pdf?token=test",
        "/object/sign/paper-grading-test/teachers/test/source.pdf?token=test#fragment",
    ],
)
def test_supabase_storage_binds_signed_url_to_the_exact_object(signed_url: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"signedURL": signed_url})

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
