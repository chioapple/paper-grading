"""阶段七 Supabase Storage 验收脚本的严格错误契约测试。"""

import httpx
import pytest

from scripts.stage7_supabase_storage_acceptance import (
    require_access_rejected,
    tamper_signed_url_token,
)


def test_access_rejection_requires_a_client_error() -> None:
    require_access_rejected(
        httpx.Response(403, json={"statusCode": "403", "message": "Unauthorized"}),
        label="私有读取检查",
    )

    with pytest.raises(RuntimeError, match="私有读取检查失败"):
        require_access_rejected(httpx.Response(200), label="私有读取检查")
    with pytest.raises(RuntimeError, match="私有读取检查失败"):
        require_access_rejected(
            httpx.Response(404, json={"message": "Not found"}),
            label="私有读取检查",
        )
    with pytest.raises(RuntimeError, match="私有读取检查失败"):
        require_access_rejected(httpx.Response(503), label="私有读取检查")
    with pytest.raises(RuntimeError, match="不是 JSON"):
        require_access_rejected(httpx.Response(403, text="denied"), label="私有读取检查")


def test_tampered_signed_url_changes_only_the_token() -> None:
    original = (
        "https://test.supabase.co/storage/v1/object/sign/bucket/key?token=header.payload.signature"
    )

    tampered = tamper_signed_url_token(original)

    assert tampered == (
        "https://test.supabase.co/storage/v1/object/sign/bucket/key?token=header.payload.signbture"
    )


def test_signed_url_without_token_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="缺少 token"):
        tamper_signed_url_token("https://test.supabase.co/storage/v1/object/sign/bucket/key")


def test_non_jwt_signed_token_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="格式无效"):
        tamper_signed_url_token(
            "https://test.supabase.co/storage/v1/object/sign/bucket/key?token=opaque"
        )
