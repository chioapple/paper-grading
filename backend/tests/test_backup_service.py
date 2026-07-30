"""供应商无关的加密逻辑备份公开行为。"""

import asyncio
import hashlib
import stat
from pathlib import Path
from uuid import UUID

import pytest

from app.maintenance.backup import (
    BackupEncryptionKey,
    BackupEnvelopeError,
    BackupFileCipher,
    BackupKeyProviderError,
    BackupScope,
    BackupService,
    BackupTargetError,
    BackupTargetReceipt,
    LogicalBackupSourceError,
    LogicalDumpMetadata,
)

BACKUP_ID = UUID("11111111-1111-4111-8111-111111111111")
PLAINTEXT = b"PGDMP\x00private logical database content"
KEY = BackupEncryptionKey(key_id="backup-key-2026-07", key=b"k" * 32)


class LogicalSource:
    async def create_dump(self, destination: Path) -> LogicalDumpMetadata:
        assert destination.exists()
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
        destination.write_bytes(PLAINTEXT)
        return LogicalDumpMetadata(
            scope=BackupScope(
                version="paper-grading-business.v1",
                included=("public.assignments", "public.audit_logs"),
                excluded=("auth.users", "storage.objects"),
            ),
            migration_version="20260726_0018",
            tool_version="pg_dump 17.5",
        )


class MemoryTarget:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.receipts: dict[str, BackupTargetReceipt] = {}

    async def put_once(
        self,
        object_key: str,
        source: Path,
        *,
        size_bytes: int,
        sha256: bytes,
    ) -> BackupTargetReceipt:
        assert stat.S_IMODE(source.stat().st_mode) == 0o600
        assert sorted(path.name for path in source.parent.iterdir()) == ["database.dump.enc"]
        content = source.read_bytes()
        assert len(content) == size_bytes
        assert hashlib.sha256(content).digest() == sha256
        if object_key in self.objects and self.objects[object_key] != content:
            raise RuntimeError("target conflict")
        self.objects[object_key] = content
        receipt = BackupTargetReceipt(
            object_key=object_key,
            version_id="memory-version-1",
            size_bytes=size_bytes,
            sha256=sha256,
        )
        self.receipts[object_key] = receipt
        return receipt

    async def stat(self, object_key: str) -> BackupTargetReceipt | None:
        return self.receipts.get(object_key)


class StaticKeyProvider:
    async def current_key(self) -> BackupEncryptionKey:
        return KEY


def test_backup_service_encrypts_uploads_verifies_and_cleans_temporary_files(
    tmp_path: Path,
) -> None:
    target = MemoryTarget()
    service = BackupService(
        source=LogicalSource(),
        target=target,
        key_provider=StaticKeyProvider(),
        temporary_root=tmp_path,
    )

    result = asyncio.run(service.create_backup(BACKUP_ID))

    assert result.status == "completed"
    assert result.error_code is None
    assert result.manifest is not None
    manifest = result.manifest
    assert manifest.scope.version == "paper-grading-business.v1"
    assert manifest.migration_version == "20260726_0018"
    assert manifest.tool_version == "pg_dump 17.5"
    assert manifest.plaintext_size_bytes == len(PLAINTEXT)
    assert manifest.plaintext_sha256 == hashlib.sha256(PLAINTEXT).digest()
    assert manifest.ciphertext_size_bytes == len(target.objects[manifest.object_key])
    assert (
        manifest.ciphertext_sha256 == hashlib.sha256(target.objects[manifest.object_key]).digest()
    )
    assert manifest.encryption_version == "aes-256-gcm-stream.v1"
    assert manifest.key_id == KEY.key_id
    assert manifest.as_dict() == {
        "schema_version": "backup-manifest.v1",
        "backup_id": str(BACKUP_ID),
        "object_key": manifest.object_key,
        "target_version_id": "memory-version-1",
        "scope": {
            "version": "paper-grading-business.v1",
            "included": ["public.assignments", "public.audit_logs"],
            "excluded": ["auth.users", "storage.objects"],
        },
        "migration_version": "20260726_0018",
        "tool_version": "pg_dump 17.5",
        "plaintext": {
            "size_bytes": len(PLAINTEXT),
            "sha256": hashlib.sha256(PLAINTEXT).hexdigest(),
        },
        "ciphertext": {
            "size_bytes": manifest.ciphertext_size_bytes,
            "sha256": manifest.ciphertext_sha256.hex(),
        },
        "encryption": {
            "version": "aes-256-gcm-stream.v1",
            "key_id": KEY.key_id,
        },
    }
    assert PLAINTEXT not in target.objects[manifest.object_key]

    encrypted_path = tmp_path / "downloaded.backup"
    decrypted_path = tmp_path / "restored.dump"
    encrypted_path.write_bytes(target.objects[manifest.object_key])
    BackupFileCipher().decrypt_file(
        encrypted_path,
        decrypted_path,
        key=KEY,
        expected_backup_id=BACKUP_ID,
    )
    assert decrypted_path.read_bytes() == PLAINTEXT
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "downloaded.backup",
        "restored.dump",
    ]


def test_backup_envelope_rejects_tampering_without_leaving_plaintext(tmp_path: Path) -> None:
    source_path = tmp_path / "database.dump"
    encrypted_path = tmp_path / "database.dump.enc"
    restored_path = tmp_path / "restored.dump"
    source_path.write_bytes(PLAINTEXT)
    cipher = BackupFileCipher()
    cipher.encrypt_file(source_path, encrypted_path, key=KEY, backup_id=BACKUP_ID)
    tampered = bytearray(encrypted_path.read_bytes())
    tampered[-17] ^= 1
    encrypted_path.write_bytes(tampered)

    with pytest.raises(
        BackupEnvelopeError,
        match="backup_envelope_authentication_failed",
    ):
        cipher.decrypt_file(
            encrypted_path,
            restored_path,
            key=KEY,
            expected_backup_id=BACKUP_ID,
        )

    assert not restored_path.exists()


def test_backup_source_failure_returns_stable_code_and_cleans_plaintext(tmp_path: Path) -> None:
    class FailingSource:
        async def create_dump(self, destination: Path) -> LogicalDumpMetadata:
            destination.write_bytes(b"partial sensitive dump")
            raise LogicalBackupSourceError("database details must stay hidden")

    target = MemoryTarget()
    result = asyncio.run(
        BackupService(
            source=FailingSource(),
            target=target,
            key_provider=StaticKeyProvider(),
            temporary_root=tmp_path,
        ).create_backup(BACKUP_ID)
    )

    assert result.status == "failed"
    assert result.error_code == "backup_source_failed"
    assert result.manifest is None
    assert target.objects == {}
    assert list(tmp_path.iterdir()) == []


def test_backup_target_failure_returns_stable_code_and_cleans_all_temporary_files(
    tmp_path: Path,
) -> None:
    class FailingTarget(MemoryTarget):
        async def put_once(
            self,
            object_key: str,
            source: Path,
            *,
            size_bytes: int,
            sha256: bytes,
        ) -> BackupTargetReceipt:
            assert source.exists()
            raise BackupTargetError("remote details must stay hidden")

    result = asyncio.run(
        BackupService(
            source=LogicalSource(),
            target=FailingTarget(),
            key_provider=StaticKeyProvider(),
            temporary_root=tmp_path,
        ).create_backup(BACKUP_ID)
    )

    assert result.status == "failed"
    assert result.error_code == "backup_target_failed"
    assert result.manifest is None
    assert list(tmp_path.iterdir()) == []


def test_backup_key_failure_never_sends_plaintext_to_target(tmp_path: Path) -> None:
    class FailingKeyProvider:
        async def current_key(self) -> BackupEncryptionKey:
            raise BackupKeyProviderError("key manager details must stay hidden")

    target = MemoryTarget()
    result = asyncio.run(
        BackupService(
            source=LogicalSource(),
            target=target,
            key_provider=FailingKeyProvider(),
            temporary_root=tmp_path,
        ).create_backup(BACKUP_ID)
    )

    assert result.status == "failed"
    assert result.error_code == "backup_encryption_failed"
    assert result.manifest is None
    assert target.objects == {}
    assert list(tmp_path.iterdir()) == []


def test_backup_rejects_a_source_that_does_not_create_a_nonempty_dump(tmp_path: Path) -> None:
    class MissingDumpSource:
        async def create_dump(self, destination: Path) -> LogicalDumpMetadata:
            assert destination.exists()
            return LogicalDumpMetadata(
                scope=BackupScope(
                    version="paper-grading-business.v1",
                    included=("public.assignments",),
                    excluded=("auth.users",),
                ),
                migration_version="20260726_0018",
                tool_version="pg_dump 17.5",
            )

    target = MemoryTarget()
    result = asyncio.run(
        BackupService(
            source=MissingDumpSource(),
            target=target,
            key_provider=StaticKeyProvider(),
            temporary_root=tmp_path,
        ).create_backup(BACKUP_ID)
    )

    assert result.status == "failed"
    assert result.error_code == "backup_source_invalid"
    assert target.objects == {}
    assert list(tmp_path.iterdir()) == []


def test_backup_is_not_completed_when_target_stat_does_not_match_upload(
    tmp_path: Path,
) -> None:
    class MismatchedTarget(MemoryTarget):
        async def stat(self, object_key: str) -> BackupTargetReceipt | None:
            receipt = await super().stat(object_key)
            assert receipt is not None
            return BackupTargetReceipt(
                object_key=receipt.object_key,
                version_id=receipt.version_id,
                size_bytes=receipt.size_bytes,
                sha256=b"x" * 32,
            )

    result = asyncio.run(
        BackupService(
            source=LogicalSource(),
            target=MismatchedTarget(),
            key_provider=StaticKeyProvider(),
            temporary_root=tmp_path,
        ).create_backup(BACKUP_ID)
    )

    assert result.status == "failed"
    assert result.error_code == "backup_target_verification_failed"
    assert result.manifest is None
    assert list(tmp_path.iterdir()) == []


def test_backup_rejects_an_unscoped_logical_dump(tmp_path: Path) -> None:
    class UnscopedSource:
        async def create_dump(self, destination: Path) -> LogicalDumpMetadata:
            destination.write_bytes(PLAINTEXT)
            return LogicalDumpMetadata(
                scope=BackupScope(version="", included=(), excluded=()),
                migration_version="",
                tool_version="",
            )

    target = MemoryTarget()
    result = asyncio.run(
        BackupService(
            source=UnscopedSource(),
            target=target,
            key_provider=StaticKeyProvider(),
            temporary_root=tmp_path,
        ).create_backup(BACKUP_ID)
    )

    assert result.status == "failed"
    assert result.error_code == "backup_source_invalid"
    assert target.objects == {}
    assert list(tmp_path.iterdir()) == []
