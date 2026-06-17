from pathlib import Path

import fitz

from pdf_json_parser.models.document import ImageBlock, ParsedDocument, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.base import BaseParser


class PyMuPDFParser(BaseParser):
    name = "pymupdf"
    TEXT_BLOCK_TYPE = 0

    def parse(self, pdf_path: Path) -> ParsedDocument:
        with fitz.open(pdf_path) as doc:
            parsed = ParsedDocument(
                source_path=str(pdf_path),
                page_count=doc.page_count,
            )

            for page_index, page in enumerate(doc, start=1):
                page_dict = page.get_text("dict", sort=True)

                for block in page_dict.get("blocks", []):
                    block_type = block.get("type")

                    if block_type == self.TEXT_BLOCK_TYPE:
                        text = self._extract_block_text(block)
                        if not text:
                            continue

                        parsed.text_blocks.append(
                            TextBlock(
                                text=text,
                                evidence=Evidence(
                                    page=page_index,
                                    bbox=self._bbox_from_sequence(block.get("bbox")),
                                    method="native_pdf_text",
                                    parser=self.name,
                                    confidence=1.0,
                                ),
                            )
                        )
                        continue

                page_images = page.get_images(full=True)
                if page_images:
                    parsed.warnings.append(
                        f"Embedded image objects detected on page {page_index}: {len(page_images)}"
                    )

                for image in page_images:
                    xref = image[0]
                    rects = page.get_image_rects(xref)

                    if rects:
                        for rect in rects:
                            parsed.image_blocks.append(
                                ImageBlock(
                                    width=image[2],
                                    height=image[3],
                                    xref=xref,
                                    bits_per_component=image[4],
                                    colorspace=image[5],
                                    extension=image[7],
                                    evidence=Evidence(
                                        page=page_index,
                                        bbox=self._bbox_from_sequence(rect),
                                        method="embedded_image_object",
                                        parser=self.name,
                                        confidence=1.0,
                                    ),
                                )
                            )
                        continue

                    parsed.image_blocks.append(
                        ImageBlock(
                            width=image[2],
                            height=image[3],
                            xref=xref,
                            bits_per_component=image[4],
                            colorspace=image[5],
                            extension=image[7],
                            evidence=Evidence(
                                page=page_index,
                                bbox=None,
                                method="embedded_image_object",
                                parser=self.name,
                                confidence=1.0,
                            ),
                        )
                    )

            return parsed

    def _extract_block_text(self, block: dict) -> str:
        lines: list[str] = []
        for line in block.get("lines", []):
            spans = [span.get("text", "") for span in line.get("spans", [])]
            line_text = "".join(spans).strip()
            if line_text:
                lines.append(line_text)
        return "\n".join(lines).strip()

    def _bbox_from_sequence(
        self,
        bbox: tuple[float, float, float, float] | list[float] | fitz.Rect | None,
    ) -> BBox | None:
        if not bbox or len(bbox) != 4:
            return None

        x0, y0, x1, y1 = bbox
        return BBox(x0=x0, y0=y0, x1=x1, y1=y1)
