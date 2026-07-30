"""阶段十三 Supabase 保留删除适配器测试。"""

import asyncio

import httpx
import pytest

from app.maintenance.retention import RetentionStorageTimeout
from app.maintenance.retention_storage import SupabaseRetentionStorage
from app.storage.supabase import SupabaseObjectStorage


def test_storage_timeout_remains_an_explicit_unknown_delete_result() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private remote detail", request=request)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            storage = SupabaseObjectStorage(
                client=client,
                storage_url="https://test-project.supabase.co/storage/v1",
                secret_key="sb_secret_test",  # pragma: allowlist secret
                bucket_name="paper-grading-test",
                signed_url_ttl_seconds=60,
            )
            await SupabaseRetentionStorage(storage).delete("teachers/owner/source.pdf")

    with pytest.raises(RetentionStorageTimeout) as error:
        asyncio.run(scenario())

    assert "private remote detail" not in str(error.value)
