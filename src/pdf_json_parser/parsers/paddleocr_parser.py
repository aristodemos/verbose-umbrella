from pathlib import Path

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.parsers.base import BaseParser


class PaddleOCRParser(BaseParser):
    name = "paddleocr"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        # TODO: OCR fallback parser.
        return ParsedDocument(
            source_path=str(pdf_path),
            page_count=0,
            warnings=["PaddleOCR parser not yet implemented"],
        )