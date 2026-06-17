from __future__ import annotations

from pathlib import Path
from typing import Any

from pdf_json_parser.models.document import ParsedDocument, TableBlock, TableCell, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.base import BaseParser


class PdfPlumberParser(BaseParser):
    name = "pdfplumber"

    def __init__(
        self,
        debug_output_dir: Path | None = None,
        debug_resolution: int = 150,
    ) -> None:
        self.debug_output_dir = debug_output_dir
        self.debug_resolution = debug_resolution

    def parse(self, pdf_path: Path) -> ParsedDocument:
        import pdfplumber

        warnings: list[str] = []
        seen_tables: set[tuple[Any, ...]] = set()

        with pdfplumber.open(str(pdf_path)) as pdf:
            parsed = ParsedDocument(
                source_path=str(pdf_path),
                page_count=len(pdf.pages),
            )

            for page_number, page in enumerate(pdf.pages, start=1):
                parsed.text_blocks.extend(self._extract_text_blocks(page, page_number))

                page_tables, page_warnings = self._extract_page_tables(page, page_number, seen_tables)
                parsed.tables.extend(page_tables)
                warnings.extend(page_warnings)

                page_images = getattr(page, "images", []) or []
                if page_images:
                    warnings.append(
                        f"Embedded image objects detected on page {page_number}: {len(page_images)}"
                    )

                if self.debug_output_dir is not None:
                    debug_warning = self._export_debug_images(page, page_number, page_tables)
                    if debug_warning is not None:
                        warnings.append(debug_warning)

            parsed.warnings.extend(warnings)
            return parsed

    def _extract_text_blocks(self, page: Any, page_number: int) -> list[TextBlock]:
        words = page.extract_words() or []
        if not words:
            return []

        lines_by_top: dict[float, list[dict[str, Any]]] = {}
        for word in words:
            top = round(float(word.get("top", 0.0)), 1)
            lines_by_top.setdefault(top, []).append(word)

        blocks: list[TextBlock] = []
        for top in sorted(lines_by_top):
            line_words = sorted(lines_by_top[top], key=lambda item: float(item.get("x0", 0.0)))
            text = " ".join(str(item.get("text", "")).strip() for item in line_words).strip()
            if not text:
                continue

            bbox = BBox(
                x0=min(float(item.get("x0", 0.0)) for item in line_words),
                y0=min(float(item.get("top", 0.0)) for item in line_words),
                x1=max(float(item.get("x1", 0.0)) for item in line_words),
                y1=max(float(item.get("bottom", 0.0)) for item in line_words),
            )
            blocks.append(
                TextBlock(
                    text=text,
                    evidence=Evidence(
                        page=page_number,
                        bbox=bbox,
                        method="native_pdf_text",
                        parser=self.name,
                        confidence=1.0,
                    ),
                )
            )

        return blocks

    def _extract_page_tables(
        self,
        page: Any,
        page_number: int,
        seen_tables: set[tuple[Any, ...]],
    ) -> tuple[list[TableBlock], list[str]]:
        warnings: list[str] = []
        tables: list[TableBlock] = []

        strategies = [
            (
                "lines",
                {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                },
                0.9,
            ),
            (
                "text",
                {
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 3,
                    "join_tolerance": 3,
                    "intersection_tolerance": 3,
                    "min_words_vertical": 2,
                    "min_words_horizontal": 1,
                },
                0.75,
            ),
        ]

        for index, (method, settings, confidence) in enumerate(strategies):
            try:
                found_tables = page.find_tables(table_settings=settings) or []
            except Exception as exc:
                warnings.append(
                    f"pdfplumber {method} table extraction failed on page {page_number}: {exc}"
                )
                continue

            for raw_table in found_tables:
                table_block = self._to_table_block(
                    raw_table=raw_table,
                    page_number=page_number,
                    method=method,
                    confidence=confidence,
                )
                if table_block is None:
                    continue

                key = self._table_key(table_block)
                if key in seen_tables:
                    continue

                seen_tables.add(key)
                tables.append(table_block)

            if tables or index == len(strategies) - 1:
                if method == "text" and tables:
                    warnings.append(
                        f"pdfplumber text-based table fallback used on page {page_number}"
                    )
                break

        return tables, warnings

    def _to_table_block(
        self,
        raw_table: Any,
        page_number: int,
        method: str,
        confidence: float,
    ) -> TableBlock | None:
        extracted_rows = raw_table.extract() if hasattr(raw_table, "extract") else None
        if not extracted_rows:
            return None

        table_bbox = self._coerce_bbox(getattr(raw_table, "bbox", None))
        evidence = Evidence(
            page=page_number,
            bbox=table_bbox,
            method=method,
            parser=self.name,
            confidence=confidence,
        )

        row_metadata = getattr(raw_table, "rows", None)
        cells: list[TableCell] = []
        for row_index, row in enumerate(extracted_rows):
            if row is None:
                continue

            raw_cells = None
            if row_metadata is not None and row_index < len(row_metadata):
                raw_cells = getattr(row_metadata[row_index], "cells", None)

            for col_index, value in enumerate(row):
                text = "" if value is None else str(value).strip()
                cell_bbox = None
                if raw_cells is not None and col_index < len(raw_cells):
                    cell_bbox = self._coerce_bbox(raw_cells[col_index])

                cells.append(
                    TableCell(
                        text=text,
                        row=row_index,
                        col=col_index,
                        evidence=Evidence(
                            page=page_number,
                            bbox=cell_bbox or table_bbox,
                            method=method,
                            parser=self.name,
                            confidence=confidence,
                        ),
                    )
                )

        if not cells:
            return None

        return TableBlock(
            page=page_number,
            cells=cells,
            evidence=evidence,
            confidence=confidence,
        )

    def _export_debug_images(
        self,
        page: Any,
        page_number: int,
        page_tables: list[TableBlock],
    ) -> str | None:
        if self.debug_output_dir is None:
            return None

        try:
            self.debug_output_dir.mkdir(parents=True, exist_ok=True)

            base_image = page.to_image(resolution=self.debug_resolution)
            base_image.save(self.debug_output_dir / f"page-{page_number:03d}.png")

            annotated_image = page.to_image(resolution=self.debug_resolution)
            for table in page_tables:
                bbox = table.evidence.bbox
                if bbox is None:
                    continue
                annotated_image.draw_rect(
                    (bbox.x0, bbox.y0, bbox.x1, bbox.y1),
                    stroke="red",
                    stroke_width=2,
                )
            annotated_image.save(self.debug_output_dir / f"page-{page_number:03d}.tables.png")
            return None
        except Exception as exc:
            return f"pdfplumber debug image export failed on page {page_number}: {exc}"

    def _coerce_bbox(self, value: Any) -> BBox | None:
        if not isinstance(value, (tuple, list)) or len(value) != 4:
            return None

        x0, y0, x1, y1 = value
        coords = (x0, y0, x1, y1)
        if any(coord is None for coord in coords):
            return None

        x0f, y0f, x1f, y1f = (float(coord) for coord in coords)
        left, right = sorted((x0f, x1f))
        top, bottom = sorted((y0f, y1f))
        return BBox(x0=left, y0=top, x1=right, y1=bottom)

    def _table_key(self, table: TableBlock) -> tuple[Any, ...]:
        bbox = table.evidence.bbox
        bbox_key = None
        if bbox is not None:
            bbox_key = (
                round(bbox.x0, 1),
                round(bbox.y0, 1),
                round(bbox.x1, 1),
                round(bbox.y1, 1),
            )

        text_key = tuple((cell.row, cell.col, cell.text) for cell in table.cells)
        return (table.page, bbox_key, text_key)
