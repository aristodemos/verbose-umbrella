from pydantic import BaseModel, ConfigDict, Field

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


class ImageBlock(BaseModel):
    kind: str = "image"
    width: int | None = None
    height: int | None = None
    xref: int | None = None
    colorspace: int | str | None = None
    bits_per_component: int | None = None
    extension: str | None = None
    evidence: Evidence


class ParsedDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_path: str
    language: str = "el"
    page_count: int
    text_blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list, alias="table")
    image_blocks: list[ImageBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def table(self) -> list[TableBlock]:
        return self.tables


