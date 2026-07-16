"""供应商 API Key 加密契约测试。"""

import base64
from uuid import UUID

import pytest

from app.security.encryption import ApiKeyCipher, EncryptedApiKeyError


def test_api_key_cipher_round_trips_without_storing_plaintext() -> None:
    master_key = base64.b64encode(bytes(range(32))).decode("ascii")
    provider_id = UUID("11111111-1111-1111-1111-111111111111")
    cipher = ApiKeyCipher.from_base64_master_key(master_key)

    encrypted = cipher.encrypt("stage-five-test-key", provider_id=provider_id)

    assert b"stage-five-test-key" not in encrypted.ciphertext
    assert len(encrypted.nonce) == 12
    assert cipher.decrypt(encrypted, provider_id=provider_id) == "stage-five-test-key"


def test_api_key_cipher_rejects_ciphertext_from_another_provider() -> None:
    master_key = base64.b64encode(bytes(range(32))).decode("ascii")
    cipher = ApiKeyCipher.from_base64_master_key(master_key)
    encrypted = cipher.encrypt(
        "stage-five-test-key",
        provider_id=UUID("11111111-1111-1111-1111-111111111111"),
    )

    with pytest.raises(EncryptedApiKeyError, match="密文验证失败"):
        cipher.decrypt(
            encrypted,
            provider_id=UUID("22222222-2222-2222-2222-222222222222"),
        )
