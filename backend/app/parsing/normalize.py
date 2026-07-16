"""上传流预检、确定性文本规范化和解析分派。"""

import hashlib
import os
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal

import msoffcrypto
from msoffcrypto.exceptions import FileFormatError

from app.parsing.models import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    DocumentParseError,
    ParsedDocument,
    ParseLimits,
    StagedDocument,
)

CHUNK_SIZE = 64 * 1024
DOCX_REQUIRED_ENTRIES = {
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
}


def normalize_text(value: str) -> str:
    """只执行不会猜测作者意图的 Unicode 和空白规范化。"""

    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\x00", "")
    return normalized.strip()


def normalize_filename(value: str) -> str:
    """只保留上传名的最后一段，并拒绝控制字符。"""

    filename = PurePosixPath(value.replace("\\", "/")).name.strip()
    if not filename or filename in {".", ".."} or len(filename) > 255:
        raise DocumentParseError("filename_invalid", "文件名无效")
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise DocumentParseError("filename_invalid", "文件名包含控制字符")
    return filename


def _detect_media_type(
    path: Path,
) -> Literal[
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
]:
    with path.open("rb") as handle:
        header = handle.read(8)
    if header.startswith(b"%PDF-"):
        return PDF_MEDIA_TYPE
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        try:
            with zipfile.ZipFile(path) as archive:
                if set(archive.namelist()) >= DOCX_REQUIRED_ENTRIES:
                    return DOCX_MEDIA_TYPE
        except (OSError, zipfile.BadZipFile):
            pass
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        try:
            with path.open("rb") as handle:
                if msoffcrypto.OfficeFile(handle).is_encrypted():
                    raise DocumentParseError("document_encrypted", "不支持加密 Word 文件")
        except DocumentParseError:
            raise
        except (FileFormatError, OSError):
            pass
    raise DocumentParseError("media_type_unsupported", "只支持有效的 DOCX 或 PDF 文件")


def _validate_media_claims(
    filename: str,
    actual_media_type: str,
    client_media_type: str | None,
) -> None:
    expected_extension = ".pdf" if actual_media_type == PDF_MEDIA_TYPE else ".docx"
    if Path(filename).suffix.lower() != expected_extension:
        raise DocumentParseError("extension_mismatch", "文件扩展名与真实格式不一致")
    if client_media_type and client_media_type not in {
        actual_media_type,
        "application/octet-stream",
    }:
        raise DocumentParseError("media_type_mismatch", "浏览器声明的格式与真实格式不一致")


@contextmanager
def stage_upload(
    stream: BinaryIO,
    *,
    original_filename: str,
    client_media_type: str | None,
    temporary_directory: Path,
    limits: ParseLimits,
) -> Iterator[StagedDocument]:
    """在上下文结束时删除分块预检产生的临时文件。"""

    staged = stage_upload_file(
        stream,
        original_filename=original_filename,
        client_media_type=client_media_type,
        temporary_directory=temporary_directory,
        limits=limits,
    )
    try:
        yield staged
    finally:
        staged.path.unlink(missing_ok=True)


def stage_upload_file(
    stream: BinaryIO,
    *,
    original_filename: str,
    client_media_type: str | None,
    temporary_directory: Path,
    limits: ParseLimits,
) -> StagedDocument:
    """分块暂存上传内容，同时执行大小、哈希和真实格式预检。"""

    filename = normalize_filename(original_filename)
    temporary_directory.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="submission-", dir=temporary_directory)
    path = Path(raw_path)
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            while chunk := stream.read(CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > limits.max_file_bytes:
                    raise DocumentParseError("file_too_large", "单个文件不能超过 20MB")
                digest.update(chunk)
                output.write(chunk)
        if size_bytes == 0:
            raise DocumentParseError("file_empty", "文件不能为空")
        media_type = _detect_media_type(path)
        _validate_media_claims(filename, media_type, client_media_type)
        return StagedDocument(
            path=path,
            original_filename=filename,
            media_type=media_type,
            size_bytes=size_bytes,
            content_sha256=digest.digest(),
        )
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def parse_document(document: StagedDocument, limits: ParseLimits) -> ParsedDocument:
    """按服务器识别出的真实格式调用严格解析器。"""

    if document.media_type == DOCX_MEDIA_TYPE:
        from app.parsing.docx import parse_docx

        return parse_docx(document, limits)
    from app.parsing.pdf import parse_pdf

    return parse_pdf(document, limits)
