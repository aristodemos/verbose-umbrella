from pathlib import Path

import fitz

from pdf_json_parser.models.document import ParsedDocument, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.base import BaseParser


class PyMuPDFParser(BaseParser):
    name = "pymupdf"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        doc = fitz.open(pdf_path)
        parsed = ParsedDocument(
            source_path=str(pdf_path),
            page_count=doc.page_count,
        )

        for page_index, page in enumerate(doc):
            blocks = page.get_text("blocks")

            for block in blocks:
                x0, y0, x1, y1, text, *_ = block
                text = text.strip()
                if not text:
                    continue

                parsed.text_blocks.append(
                    TextBlock(
                        text=text,
                        evidence=Evidence(
                            page=page_index + 1,
                            bbox=BBox(x0=x0, y0=y0, x1=x1, y1=y1),
                            method="native_pdf_text",
                            parser=self.name,
                            confidence=1.0,
                        ),
                    )
                )

            image_count = len(page.get_images(full=True))
            if image_count:
                parsed.warnings.append(
                    f"Embedded image objects detected on page {page_index + 1}: {image_count}"
                )

        return parsed