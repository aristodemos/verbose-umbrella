from pathlib import Path

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.parsers.base import BaseParser


class CamelotParser(BaseParser):
    name = "camelot"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        # TODO: run lattice and stream, convert tables to TableBlock.
        return ParsedDocument(
            source_path=str(pdf_path),
            page_count=0,
            warnings=["Camelot parser not yet implemented"],
        )