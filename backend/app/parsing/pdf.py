"""PDF 结构验证和分页文本块解析。"""

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

from app.parsing.models import (
    PDF_MEDIA_TYPE,
    DocumentBlock,
    DocumentParseError,
    ParsedDocument,
    ParseLimits,
    PdfTextBlockLocator,
    StagedDocument,
)
from app.parsing.normalize import normalize_text

FORBIDDEN_PDF_KEYS = frozenset(
    {
        "/AA",
        "/AcroForm",
        "/EmbeddedFiles",
        "/JavaScript",
        "/Launch",
        "/OpenAction",
        "/RichMedia",
        "/XFA",
    }
)
FORBIDDEN_PDF_ACTIONS = frozenset(
    {
        "/GoToE",
        "/GoToR",
        "/ImportData",
        "/JavaScript",
        "/Launch",
        "/Rendition",
        "/SubmitForm",
        "/URI",
    }
)
MAX_PDF_OBJECTS_INSPECTED = 100_000


def _reject_active_content(reader: PdfReader) -> None:
    """结构化遍历 PDF 对象图，拒绝脚本、外部动作、附件和交互表单。"""

    stack: list[object] = [reader.trailer]
    seen_indirect: set[tuple[int, int]] = set()
    seen_direct: set[int] = set()
    inspected = 0
    while stack:
        current = stack.pop()
        if isinstance(current, IndirectObject):
            reference = (current.idnum, current.generation)
            if reference in seen_indirect:
                continue
            seen_indirect.add(reference)
            current = current.get_object()
        elif isinstance(current, (DictionaryObject, ArrayObject)):
            identity = id(current)
            if identity in seen_direct:
                continue
            seen_direct.add(identity)

        inspected += 1
        if inspected > MAX_PDF_OBJECTS_INSPECTED:
            raise DocumentParseError("pdf_structure_too_complex", "PDF 对象结构超过安全限制")
        if isinstance(current, DictionaryObject):
            keys = {str(key) for key in current}
            action = current.get("/S")
            if keys & FORBIDDEN_PDF_KEYS or str(action) in FORBIDDEN_PDF_ACTIONS:
                raise DocumentParseError(
                    "pdf_active_content_unsupported",
                    "PDF 包含脚本、外部动作、附件或交互表单",
                )
            stack.extend(current.values())
        elif isinstance(current, ArrayObject):
            stack.extend(current)


def parse_pdf(document: StagedDocument, limits: ParseLimits) -> ParsedDocument:
    """严格读取全部页面，并把每个可提取文本行保存为页内文本块。"""

    try:
        reader = PdfReader(document.path, strict=True)
        if reader.is_encrypted:
            raise DocumentParseError("document_encrypted", "不支持加密 PDF")
        page_count = len(reader.pages)
        if page_count == 0:
            raise DocumentParseError("document_empty", "PDF 没有页面")
        if page_count > limits.max_pdf_pages:
            raise DocumentParseError("pdf_pages_too_many", "PDF 页数超过限制")
        _reject_active_content(reader)

        blocks: list[DocumentBlock] = []
        character_count = 0
        scanned_pages: list[int] = []
        unextractable_pages: list[int] = []
        with pdfplumber.open(document.path) as layout_document:
            if len(layout_document.pages) != page_count:
                raise DocumentParseError("pdf_parse_failed", "PDF 页面目录不一致")
            for page_number, layout_page in enumerate(layout_document.pages, start=1):
                extracted_lines = layout_page.extract_text_lines(
                    layout=True,
                    return_chars=False,
                )
                page_block_number = 0
                for extracted_line in extracted_lines:
                    text = normalize_text(str(extracted_line["text"]))
                    if not text:
                        continue
                    character_count += len(text)
                    if character_count > limits.max_characters:
                        raise DocumentParseError(
                            "document_text_too_large",
                            "可提取文本超过限制",
                        )
                    if len(blocks) >= limits.max_blocks:
                        raise DocumentParseError(
                            "document_blocks_too_many",
                            "可定位文本块超过限制",
                        )
                    page_block_number += 1
                    blocks.append(
                        DocumentBlock(
                            block_id=f"b{len(blocks) + 1:06d}",
                            text=text,
                            locator=PdfTextBlockLocator(
                                page=page_number,
                                block=page_block_number,
                                bbox=(
                                    round(float(extracted_line["x0"]), 4),
                                    round(float(extracted_line["top"]), 4),
                                    round(float(extracted_line["x1"]), 4),
                                    round(float(extracted_line["bottom"]), 4),
                                ),
                            ),
                        )
                    )
                if page_block_number == 0:
                    if layout_page.images:
                        scanned_pages.append(page_number)
                    elif layout_page.chars or layout_page.curves or layout_page.rects:
                        unextractable_pages.append(page_number)
        if scanned_pages:
            code = "pdf_partial_scan_unsupported" if blocks else "pdf_scan_unsupported"
            raise DocumentParseError(code, "不支持扫描型 PDF，且不会自动执行 OCR")
        if unextractable_pages:
            raise DocumentParseError("pdf_text_unextractable", "PDF 页面文字无法可靠提取")
        if not blocks:
            raise DocumentParseError("document_empty", "PDF 没有可提取文字")
        return ParsedDocument(
            media_type=PDF_MEDIA_TYPE,
            page_count=page_count,
            character_count=character_count,
            blocks=blocks,
        )
    except DocumentParseError:
        raise
    except (
        FileNotDecryptedError,
        PDFPasswordIncorrect,
        PDFSyntaxError,
        PdfReadError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        raise DocumentParseError("pdf_parse_failed", "PDF 文件损坏或无法解析") from error
