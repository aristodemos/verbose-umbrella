from pathlib import Path

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.parsers.base import BaseParser


class DoclingParser(BaseParser):
    name = "Docling"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        # Placeholder implementation - replace with actual Docling parsing logic.
        # For now, it returns an empty ParsedDocument with just the source path.
        return ParsedDocument(
            source_path=str(pdf_path),
            language="el",
            page_count=0,
            text_blocks=[],
            table=[],
            warnings=["Docling parser is not yet implemented."],
        )