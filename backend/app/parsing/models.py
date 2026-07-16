"""论文预检和规范文本块的公共契约。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DOCX_MEDIA_TYPE: Final[
    Literal["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE: Final[Literal["application/pdf"]] = "application/pdf"
DOCUMENT_SCHEMA_VERSION: Final[Literal["document-blocks.v1"]] = "document-blocks.v1"
PARSER_VERSION: Final[Literal["1"]] = "1"


@dataclass(frozen=True, slots=True)
class ParseLimits:
    """阶段七固定的资源上限。"""

    max_file_bytes: int = 20 * 1024 * 1024
    max_pdf_pages: int = 200
    max_characters: int = 500_000
    max_blocks: int = 50_000
    max_zip_entries: int = 10_000
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_zip_compression_ratio: int = 200


@dataclass(frozen=True, slots=True)
class StagedDocument:
    """流式预检后保存在临时目录中的论文。"""

    path: Path
    original_filename: str
    media_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    size_bytes: int
    content_sha256: bytes


class DocumentParseError(ValueError):
    """稳定暴露给上传接口的文档拒绝原因。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DocxParagraphLocator(BaseModel):
    """DOCX 正文段落位置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["docx_paragraph"] = "docx_paragraph"
    paragraph: int = Field(ge=1)


class DocxTableParagraphLocator(BaseModel):
    """DOCX 表格单元格段落位置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["docx_table_paragraph"] = "docx_table_paragraph"
    table: int = Field(ge=1)
    row: int = Field(ge=1)
    column: int = Field(ge=1)
    paragraph: int = Field(ge=1)


class PdfTextBlockLocator(BaseModel):
    """PDF 页内文本块位置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["pdf_text_block"] = "pdf_text_block"
    page: int = Field(ge=1)
    block: int = Field(ge=1)
    bbox: tuple[float, float, float, float]


DocumentLocator = Annotated[
    DocxParagraphLocator | DocxTableParagraphLocator | PdfTextBlockLocator,
    Field(discriminator="kind"),
]


class DocumentBlock(BaseModel):
    """模型评分和教师证据定位共享的最小文本单元。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str = Field(pattern=r"^b[0-9]{6}$")
    text: str = Field(min_length=1, max_length=500_000)
    locator: DocumentLocator


class ParsedDocument(BaseModel):
    """写入 Supabase Storage 的版本化规范文本对象。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["document-blocks.v1"] = DOCUMENT_SCHEMA_VERSION
    parser_version: Literal["1"] = PARSER_VERSION
    media_type: Literal[
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
    page_count: int | None
    character_count: int = Field(gt=0, le=500_000)
    blocks: tuple[DocumentBlock, ...] = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def validate_block_ids(self) -> "ParsedDocument":
        expected_ids = [f"b{index:06d}" for index in range(1, len(self.blocks) + 1)]
        actual_ids = [block.block_id for block in self.blocks]
        if actual_ids != expected_ids:
            raise ValueError("文本块 ID 必须唯一且连续")
        if self.character_count != sum(len(block.text) for block in self.blocks):
            raise ValueError("字符数必须等于文本块原文长度之和")
        if self.media_type == PDF_MEDIA_TYPE:
            if self.page_count is None or not 1 <= self.page_count <= 200:
                raise ValueError("PDF 页数必须在一至二百页之间")
        elif self.page_count is not None:
            raise ValueError("DOCX 不得伪造固定页数")
        return self
