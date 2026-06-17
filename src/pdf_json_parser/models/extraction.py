from typing import Any

from pydantic import BaseModel, Field

from pdf_json_parser.models.document import ParsedDocument


class ExtractionResult(BaseModel):
    document: ParsedDocument
    extracted_json: dict[str, Any]
    schema_errors: list[str] = []
    warnings: list[str] = []
    score: float | None = Field(default=None, ge=0.0, le=1.0, description="Confidence score of the overall extraction process, if applicable.")
    