from pathlib import Path

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.parsers.base import BaseParser


class PdfPlumberParser(BaseParser):
    name = "pdfplumber"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        # TODO: implement detailed block and table extraction.
        return ParsedDocument(
            source_path=str(pdf_path),
            page_count=0,
            warnings=["pdfplumber parser not yet implemented"],
        )