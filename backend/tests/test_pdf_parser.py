"""阶段七 PDF 预检与解析契约测试。"""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.parsing.models import PDF_MEDIA_TYPE, DocumentParseError, ParseLimits
from app.parsing.normalize import parse_document, stage_upload


def build_text_pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    document.drawString(72, 760, "First page line")
    document.showPage()
    document.drawString(72, 760, "Second page line")
    document.save()
    return output.getvalue()


def build_two_position_pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    document.drawString(72, 760, "Top line")
    document.drawString(250, 200, "Lower line")
    document.save()
    return output.getvalue()


def build_scanned_pdf() -> bytes:
    image_output = BytesIO()
    Image.new("RGB", (20, 20), "black").save(image_output, format="PNG")
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    document.drawImage(ImageReader(BytesIO(image_output.getvalue())), 72, 700, 200, 100)
    document.save()
    return output.getvalue()


def build_blank_pdf() -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    document.showPage()
    document.save()
    return output.getvalue()


def build_partial_scan_pdf() -> bytes:
    image_output = BytesIO()
    Image.new("RGB", (20, 20), "black").save(image_output, format="PNG")
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=A4)
    document.drawString(72, 760, "Text page")
    document.showPage()
    document.drawImage(ImageReader(BytesIO(image_output.getvalue())), 72, 700, 200, 100)
    document.save()
    return output.getvalue()


def build_encrypted_pdf() -> bytes:
    reader = PdfReader(BytesIO(build_text_pdf()))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_upload_is_parsed_into_page_located_text_blocks(tmp_path: Path) -> None:
    content = build_text_pdf()

    with stage_upload(
        BytesIO(content),
        original_filename="essay.pdf",
        client_media_type=PDF_MEDIA_TYPE,
        temporary_directory=tmp_path,
        limits=ParseLimits(),
    ) as staged:
        parsed = parse_document(staged, ParseLimits())

    assert parsed.page_count == 2
    assert [block.block_id for block in parsed.blocks] == ["b000001", "b000002"]
    assert [block.text for block in parsed.blocks] == [
        "First page line",
        "Second page line",
    ]
    locators = [block.locator.model_dump(mode="json") for block in parsed.blocks]
    assert [(locator["page"], locator["block"]) for locator in locators] == [(1, 1), (2, 1)]
    for locator in locators:
        x0, top, x1, bottom = locator["bbox"]
        assert x0 == pytest.approx(72.0)
        assert 100 < x1 < 200
        assert 0 < top < bottom < 100


def test_scanned_pdf_is_rejected_without_ocr(tmp_path: Path) -> None:
    with (
        stage_upload(
            BytesIO(build_scanned_pdf()),
            original_filename="scan.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as staged,
        pytest.raises(DocumentParseError) as error,
    ):
        parse_document(staged, ParseLimits())

    assert error.value.code == "pdf_scan_unsupported"


def test_pdf_blocks_on_the_same_page_keep_distinct_text_coordinates(tmp_path: Path) -> None:
    with stage_upload(
        BytesIO(build_two_position_pdf()),
        original_filename="two-positions.pdf",
        client_media_type=PDF_MEDIA_TYPE,
        temporary_directory=tmp_path,
        limits=ParseLimits(),
    ) as staged:
        parsed = parse_document(staged, ParseLimits())

    assert [block.text for block in parsed.blocks] == ["Top line", "Lower line"]
    first, second = [block.locator.model_dump(mode="json") for block in parsed.blocks]
    assert first["page"] == second["page"] == 1
    assert first["bbox"] != second["bbox"]
    assert first["bbox"][1] < second["bbox"][1]


def test_blank_and_damaged_pdfs_are_rejected_explicitly(tmp_path: Path) -> None:
    with (
        stage_upload(
            BytesIO(build_blank_pdf()),
            original_filename="blank.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as blank,
        pytest.raises(DocumentParseError) as blank_error,
    ):
        parse_document(blank, ParseLimits())
    assert blank_error.value.code == "document_empty"

    with (
        stage_upload(
            BytesIO(b"%PDF-1.7\nnot-a-valid-pdf"),
            original_filename="damaged.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as damaged,
        pytest.raises(DocumentParseError) as damaged_error,
    ):
        parse_document(damaged, ParseLimits())
    assert damaged_error.value.code == "pdf_parse_failed"


def test_pdf_with_a_scanned_page_is_rejected_without_partial_output(tmp_path: Path) -> None:
    with (
        stage_upload(
            BytesIO(build_partial_scan_pdf()),
            original_filename="partial-scan.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as staged,
        pytest.raises(DocumentParseError) as error,
    ):
        parse_document(staged, ParseLimits())

    assert error.value.code == "pdf_partial_scan_unsupported"


def test_encrypted_pdf_and_page_limit_are_rejected_explicitly(tmp_path: Path) -> None:
    with (
        stage_upload(
            BytesIO(build_encrypted_pdf()),
            original_filename="encrypted.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as encrypted,
        pytest.raises(DocumentParseError) as encrypted_error,
    ):
        parse_document(encrypted, ParseLimits())
    assert encrypted_error.value.code == "document_encrypted"

    with (
        stage_upload(
            BytesIO(build_text_pdf()),
            original_filename="long.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as long_pdf,
        pytest.raises(DocumentParseError) as page_error,
    ):
        parse_document(long_pdf, ParseLimits(max_pdf_pages=1))
    assert page_error.value.code == "pdf_pages_too_many"


def test_pdf_text_and_block_limits_are_enforced(tmp_path: Path) -> None:
    with (
        stage_upload(
            BytesIO(build_text_pdf()),
            original_filename="text-limit.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as text_limited,
        pytest.raises(DocumentParseError) as text_error,
    ):
        parse_document(text_limited, ParseLimits(max_characters=1))
    assert text_error.value.code == "document_text_too_large"

    with (
        stage_upload(
            BytesIO(build_text_pdf()),
            original_filename="block-limit.pdf",
            client_media_type=PDF_MEDIA_TYPE,
            temporary_directory=tmp_path,
            limits=ParseLimits(),
        ) as block_limited,
        pytest.raises(DocumentParseError) as block_error,
    ):
        parse_document(block_limited, ParseLimits(max_blocks=1))
    assert block_error.value.code == "document_blocks_too_many"
