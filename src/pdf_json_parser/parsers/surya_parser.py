from pathlib import Path

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.parsers.base import BaseParser


class SuryaParser(BaseParser):
    name = "surya"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        # TODO: OCR/layout/table recognition for low-confidence pages or image regions.
        return ParsedDocument(
            source_path=str(pdf_path),
            page_count=0,
            warnings=["Surya OCR parser not yet implemented"],
        )