"""供应商 API Key 的版本化 AES-GCM 加密。"""

import base64
import binascii
import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENVELOPE_VERSION = b"\x01"
NONCE_BYTES = 12
MASTER_KEY_BYTES = 32
ASSOCIATED_DATA_PREFIX = b"paper-grading:provider-api-key:v1:"


class EncryptionConfigurationError(ValueError):
    """主密钥配置不符合要求。"""


class EncryptedApiKeyError(ValueError):
    """密文损坏、版本不支持或不属于当前供应商。"""


@dataclass(frozen=True, slots=True)
class EncryptedApiKey:
    """可直接写入 provider_configs 的密文材料。"""

    ciphertext: bytes
    nonce: bytes


class ApiKeyCipher:
    """把加解密细节封装在一个小接口中。"""

    def __init__(self, master_key: bytes) -> None:
        if len(master_key) != MASTER_KEY_BYTES:
            raise EncryptionConfigurationError("供应商主密钥必须是 32 字节")
        self._cipher = AESGCM(master_key)

    @classmethod
    def from_base64_master_key(cls, value: str) -> "ApiKeyCipher":
        """从严格 Base64 环境变量创建加密器。"""

        try:
            master_key = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise EncryptionConfigurationError("供应商主密钥必须是有效 Base64") from error
        return cls(master_key)

    @staticmethod
    def _associated_data(provider_id: UUID) -> bytes:
        return ASSOCIATED_DATA_PREFIX + provider_id.bytes

    def encrypt(self, api_key: str, *, provider_id: UUID) -> EncryptedApiKey:
        """使用随机 nonce 加密，并把密文绑定到供应商记录。"""

        if not api_key:
            raise ValueError("API Key 不能为空")
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = self._cipher.encrypt(
            nonce,
            api_key.encode("utf-8"),
            self._associated_data(provider_id),
        )
        return EncryptedApiKey(ciphertext=ENVELOPE_VERSION + ciphertext, nonce=nonce)

    def decrypt(self, encrypted: EncryptedApiKey, *, provider_id: UUID) -> str:
        """只解密当前版本且属于指定供应商记录的密文。"""

        if len(encrypted.nonce) != NONCE_BYTES or not encrypted.ciphertext.startswith(
            ENVELOPE_VERSION
        ):
            raise EncryptedApiKeyError("API Key 密文格式无效")
        try:
            plaintext = self._cipher.decrypt(
                encrypted.nonce,
                encrypted.ciphertext[len(ENVELOPE_VERSION) :],
                self._associated_data(provider_id),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as error:
            raise EncryptedApiKeyError("API Key 密文验证失败") from error
