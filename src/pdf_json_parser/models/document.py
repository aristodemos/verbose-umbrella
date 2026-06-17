from pydantic import BaseModel, Field

from pdf_json_parser.models.geometry import Evidence


class TextBlock(BaseModel):
    text: str
    kind: str = "paragraph"
    evidence: Evidence


class TableCell(BaseModel):
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    evidence: Evidence | None = None


class TableBlock(BaseModel):
    title: str | None = None
    page: int
    cells: list[TableCell]
    evidence: Evidence
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score of the table extraction method, if applicable.")


class ParsedDocument(BaseModel):
    source_path: str
    language: str = "el"
    page_count: int
    # text_blocks: list[TextBlock] = Field(default_factory=list)
    text_blocks: list[TextBlock] = []
    # table_blocks: list[TableBlock] = Field(default_factory=list)
    table: list[TableBlock] = []
    warnings: list[str] = []


