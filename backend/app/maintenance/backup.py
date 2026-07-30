"""目标无关的逻辑备份、流式加密与完整性校验。"""

from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Literal, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

FILE_CHUNK_BYTES = 1024 * 1024
ENVELOPE_MAGIC = b"PGBACKUP"
ENVELOPE_VERSION_BYTE = 1
ENCRYPTION_VERSION = "aes-256-gcm-stream.v1"
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True, slots=True)
class BackupScope:
    """逻辑转储精确包含和排除的范围。"""

    version: str
    included: tuple[str, ...]
    excluded: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogicalDumpMetadata:
    """由逻辑转储来源证明的非敏感元数据。"""

    scope: BackupScope
    migration_version: str
    tool_version: str


@dataclass(frozen=True, slots=True)
class BackupEncryptionKey:
    """独立备份密钥材料；key_id 用于轮换，密钥不得进入清单。"""

    key_id: str
    key: bytes

    def __post_init__(self) -> None:
        if not KEY_ID_PATTERN.fullmatch(self.key_id):
            raise ValueError("backup_key_id_invalid")
        if len(self.key) != KEY_BYTES:
            raise ValueError("backup_key_invalid")


@dataclass(frozen=True, slots=True)
class BackupTargetReceipt:
    """目标存储对一个不可覆盖对象的确认。"""

    object_key: str
    version_id: str
    size_bytes: int
    sha256: bytes


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """可持久化但不含凭据和业务正文的备份清单。"""

    backup_id: UUID
    object_key: str
    target_version_id: str
    scope: BackupScope
    migration_version: str
    tool_version: str
    plaintext_size_bytes: int
    plaintext_sha256: bytes
    ciphertext_size_bytes: int
    ciphertext_sha256: bytes
    encryption_version: str
    key_id: str

    def as_dict(self) -> dict[str, object]:
        """转换为可审计且不含密钥材料的稳定清单。"""

        return {
            "schema_version": "backup-manifest.v1",
            "backup_id": str(self.backup_id),
            "object_key": self.object_key,
            "target_version_id": self.target_version_id,
            "scope": {
                "version": self.scope.version,
                "included": list(self.scope.included),
                "excluded": list(self.scope.excluded),
            },
            "migration_version": self.migration_version,
            "tool_version": self.tool_version,
            "plaintext": {
                "size_bytes": self.plaintext_size_bytes,
                "sha256": self.plaintext_sha256.hex(),
            },
            "ciphertext": {
                "size_bytes": self.ciphertext_size_bytes,
                "sha256": self.ciphertext_sha256.hex(),
            },
            "encryption": {
                "version": self.encryption_version,
                "key_id": self.key_id,
            },
        }


@dataclass(frozen=True, slots=True)
class BackupResult:
    """调用方只接收稳定状态和错误码。"""

    status: Literal["completed", "failed"]
    manifest: BackupManifest | None = None
    error_code: str | None = None


class LogicalBackupSource(Protocol):
    """生成一个逻辑数据库转储，具体数据库工具由适配器负责。"""

    async def create_dump(self, destination: Path) -> LogicalDumpMetadata: ...


class BackupKeyProvider(Protocol):
    """从用户确认的独立托管位置取得当前备份密钥。"""

    async def current_key(self) -> BackupEncryptionKey: ...


class BackupTarget(Protocol):
    """供应商无关、禁用覆盖的备份对象目标。"""

    async def put_once(
        self,
        object_key: str,
        source: Path,
        *,
        size_bytes: int,
        sha256: bytes,
    ) -> BackupTargetReceipt: ...

    async def stat(self, object_key: str) -> BackupTargetReceipt | None: ...


@dataclass(frozen=True, slots=True)
class BackupRestoreProof:
    """隔离恢复适配器返回的证明；成功前不能把备份标为可恢复。"""

    backup_id: UUID
    status: Literal["verified", "failed"]
    environment_id: str
    check_version: str
    error_code: str | None = None


class BackupRestoreVerifier(Protocol):
    """真实隔离恢复由后续、经授权的适配器实现。"""

    async def verify(self, manifest: BackupManifest) -> BackupRestoreProof: ...


class BackupCleanupTarget(Protocol):
    """备份清理只能按已记录版本与密文哈希条件删除。"""

    async def delete_if_version(
        self,
        object_key: str,
        *,
        version_id: str,
        sha256: bytes,
    ) -> bool: ...


class BackupEnvelopeError(ValueError):
    """加密包损坏、密钥错误或身份不匹配。"""


class LogicalBackupSourceError(RuntimeError):
    """逻辑转储来源失败；异常正文不得进入状态或日志。"""


class BackupTargetError(RuntimeError):
    """备份目标操作失败；异常正文不得进入状态或日志。"""


class BackupKeyProviderError(RuntimeError):
    """备份密钥托管位置不可用；异常正文不得进入状态或日志。"""


def _file_facts(path: Path) -> tuple[int, bytes]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(FILE_CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.digest()


def _valid_dump_metadata(metadata: LogicalDumpMetadata) -> bool:
    included = metadata.scope.included
    excluded = metadata.scope.excluded
    return (
        bool(metadata.scope.version.strip())
        and bool(metadata.migration_version.strip())
        and bool(metadata.tool_version.strip())
        and bool(included)
        and bool(excluded)
        and all(value.strip() for value in (*included, *excluded))
        and len(set(included)) == len(included)
        and len(set(excluded)) == len(excluded)
        and set(included).isdisjoint(excluded)
    )


def _open_private_output(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


class BackupFileCipher:
    """使用独立 AES-256-GCM envelope 流式处理逻辑转储。"""

    @staticmethod
    def _header(backup_id: UUID, key_id: str, nonce: bytes) -> bytes:
        key_id_bytes = key_id.encode("ascii")
        return (
            ENVELOPE_MAGIC
            + bytes((ENVELOPE_VERSION_BYTE,))
            + backup_id.bytes
            + struct.pack(">H", len(key_id_bytes))
            + key_id_bytes
            + nonce
        )

    def encrypt_file(
        self,
        source_path: Path,
        destination_path: Path,
        *,
        key: BackupEncryptionKey,
        backup_id: UUID,
    ) -> None:
        """加密到新文件；固定头部作为 AAD，正文不会一次进入内存。"""

        nonce = os.urandom(NONCE_BYTES)
        header = self._header(backup_id, key.key_id, nonce)
        encryptor = Cipher(algorithms.AES(key.key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(header)
        with (
            source_path.open("rb") as source,
            _open_private_output(destination_path) as destination,
        ):
            destination.write(header)
            while chunk := source.read(FILE_CHUNK_BYTES):
                destination.write(encryptor.update(chunk))
            destination.write(encryptor.finalize())
            destination.write(encryptor.tag)

    def decrypt_file(
        self,
        source_path: Path,
        destination_path: Path,
        *,
        key: BackupEncryptionKey,
        expected_backup_id: UUID,
    ) -> None:
        """验证 envelope 身份和 GCM tag 后生成逻辑转储。"""

        minimum_header_bytes = len(ENVELOPE_MAGIC) + 1 + 16 + 2
        destination_created = False
        try:
            total_size = source_path.stat().st_size
            with source_path.open("rb") as source:
                fixed = source.read(minimum_header_bytes)
                if len(fixed) != minimum_header_bytes:
                    raise BackupEnvelopeError("backup_envelope_invalid")
                if fixed[: len(ENVELOPE_MAGIC)] != ENVELOPE_MAGIC:
                    raise BackupEnvelopeError("backup_envelope_invalid")
                if fixed[len(ENVELOPE_MAGIC)] != ENVELOPE_VERSION_BYTE:
                    raise BackupEnvelopeError("backup_encryption_version_unsupported")
                offset = len(ENVELOPE_MAGIC) + 1
                actual_backup_id = UUID(bytes=fixed[offset : offset + 16])
                offset += 16
                key_id_size = struct.unpack(">H", fixed[offset : offset + 2])[0]
                key_id_bytes = source.read(key_id_size)
                nonce = source.read(NONCE_BYTES)
                if len(key_id_bytes) != key_id_size or len(nonce) != NONCE_BYTES:
                    raise BackupEnvelopeError("backup_envelope_invalid")
                try:
                    actual_key_id = key_id_bytes.decode("ascii")
                except UnicodeDecodeError as error:
                    raise BackupEnvelopeError("backup_envelope_invalid") from error
                if actual_backup_id != expected_backup_id or actual_key_id != key.key_id:
                    raise BackupEnvelopeError("backup_envelope_identity_mismatch")
                header = fixed + key_id_bytes + nonce
                ciphertext_size = total_size - len(header) - TAG_BYTES
                if ciphertext_size < 0:
                    raise BackupEnvelopeError("backup_envelope_invalid")
                source.seek(total_size - TAG_BYTES)
                tag = source.read(TAG_BYTES)
                if len(tag) != TAG_BYTES:
                    raise BackupEnvelopeError("backup_envelope_invalid")
                source.seek(len(header))
                decryptor = Cipher(algorithms.AES(key.key), modes.GCM(nonce, tag)).decryptor()
                decryptor.authenticate_additional_data(header)
                remaining = ciphertext_size
                with _open_private_output(destination_path) as destination:
                    destination_created = True
                    while remaining:
                        chunk = source.read(min(FILE_CHUNK_BYTES, remaining))
                        if not chunk:
                            raise BackupEnvelopeError("backup_envelope_invalid")
                        remaining -= len(chunk)
                        destination.write(decryptor.update(chunk))
                    destination.write(decryptor.finalize())
        except InvalidTag as error:
            if destination_created:
                destination_path.unlink(missing_ok=True)
            raise BackupEnvelopeError("backup_envelope_authentication_failed") from error
        except (OSError, ValueError):
            if destination_created:
                destination_path.unlink(missing_ok=True)
            raise


class BackupService:
    """生成、加密、不可覆盖上传并核对目标回执。"""

    def __init__(
        self,
        *,
        source: LogicalBackupSource,
        target: BackupTarget,
        key_provider: BackupKeyProvider,
        temporary_root: Path,
        cipher: BackupFileCipher | None = None,
    ) -> None:
        self._source = source
        self._target = target
        self._key_provider = key_provider
        self._temporary_root = temporary_root
        self._cipher = cipher or BackupFileCipher()

    async def create_backup(self, backup_id: UUID) -> BackupResult:
        """完成一次目标无关备份；临时明文和密文始终由上下文清理。"""

        object_key = f"database-backups/{backup_id}.pgdump.aes256gcm"
        with TemporaryDirectory(
            prefix="paper-grading-backup-",
            dir=self._temporary_root,
        ) as directory:
            working_directory = Path(directory)
            plaintext_path = working_directory / "database.dump"
            encrypted_path = working_directory / "database.dump.enc"
            plaintext_path.touch(mode=0o600, exist_ok=False)
            try:
                metadata = await self._source.create_dump(plaintext_path)
            except LogicalBackupSourceError:
                return BackupResult(status="failed", error_code="backup_source_failed")
            if not _valid_dump_metadata(metadata):
                return BackupResult(status="failed", error_code="backup_source_invalid")
            try:
                plaintext_size, plaintext_sha256 = _file_facts(plaintext_path)
            except OSError:
                return BackupResult(status="failed", error_code="backup_source_invalid")
            if plaintext_size <= 0:
                return BackupResult(status="failed", error_code="backup_source_invalid")
            try:
                key = await self._key_provider.current_key()
                self._cipher.encrypt_file(
                    plaintext_path,
                    encrypted_path,
                    key=key,
                    backup_id=backup_id,
                )
                ciphertext_size, ciphertext_sha256 = _file_facts(encrypted_path)
                plaintext_path.unlink()
            except (BackupKeyProviderError, BackupEnvelopeError, OSError):
                return BackupResult(status="failed", error_code="backup_encryption_failed")
            try:
                receipt = await self._target.put_once(
                    object_key,
                    encrypted_path,
                    size_bytes=ciphertext_size,
                    sha256=ciphertext_sha256,
                )
                observed = await self._target.stat(object_key)
            except BackupTargetError:
                return BackupResult(status="failed", error_code="backup_target_failed")
            if (
                observed is None
                or observed.object_key != object_key
                or not observed.version_id
                or observed.size_bytes != ciphertext_size
                or observed.sha256 != ciphertext_sha256
                or receipt != observed
            ):
                return BackupResult(status="failed", error_code="backup_target_verification_failed")
            return BackupResult(
                status="completed",
                manifest=BackupManifest(
                    backup_id=backup_id,
                    object_key=object_key,
                    target_version_id=observed.version_id,
                    scope=metadata.scope,
                    migration_version=metadata.migration_version,
                    tool_version=metadata.tool_version,
                    plaintext_size_bytes=plaintext_size,
                    plaintext_sha256=plaintext_sha256,
                    ciphertext_size_bytes=ciphertext_size,
                    ciphertext_sha256=ciphertext_sha256,
                    encryption_version=ENCRYPTION_VERSION,
                    key_id=key.key_id,
                ),
            )
