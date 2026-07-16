"""阶段七上传流预检测试。"""

from io import BytesIO
from pathlib import Path

import pytest

from app.parsing.models import PDF_MEDIA_TYPE, DocumentParseError, ParseLimits
from app.parsing.normalize import stage_upload


def test_staging_rejects_empty_and_oversized_files_without_temp_leaks(tmp_path: Path) -> None:
    with (
        pytest.raises(DocumentParseError) as empty_error,
        stage_upload(
            BytesIO(b""),
            original_filename="empty.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(max_file_bytes=8),
        ),
    ):
        pass
    assert empty_error.value.code == "file_empty"

    with (
        pytest.raises(DocumentParseError) as size_error,
        stage_upload(
            BytesIO(b"%PDF-1234"),
            original_filename="large.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(max_file_bytes=8),
        ),
    ):
        pass
    assert size_error.value.code == "file_too_large"

    with stage_upload(
        BytesIO(b"%PDF-1234"),
        original_filename="at-limit.pdf",
        client_media_type=PDF_MEDIA_TYPE,
        temporary_directory=tmp_path,
        limits=ParseLimits(max_file_bytes=9),
    ) as staged:
        assert staged.size_bytes == 9
    assert list(tmp_path.iterdir()) == []


def test_staging_rejects_extension_and_client_mime_mismatches(tmp_path: Path) -> None:
    with (
        pytest.raises(DocumentParseError) as extension_error,
        stage_upload(
            BytesIO(b"%PDF-test"),
            original_filename="forged.docx",
            client_media_type="application/octet-stream",
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ),
    ):
        pass
    assert extension_error.value.code == "extension_mismatch"

    with (
        pytest.raises(DocumentParseError) as mime_error,
        stage_upload(
            BytesIO(b"%PDF-test"),
            original_filename="essay.pdf",
            client_media_type="text/plain",
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ),
    ):
        pass
    assert mime_error.value.code == "media_type_mismatch"
