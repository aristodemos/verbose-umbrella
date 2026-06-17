from pathlib import Path

import fitz

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.models.document import TableBlock
from pdf_json_parser.models.document import TableCell
from pdf_json_parser.models.geometry import BBox
from pdf_json_parser.models.geometry import Evidence
from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.parsers.base import BaseParser


class CamelotParser(BaseParser):
    name = "camelot"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        import camelot

        page_count = self._get_page_count(pdf_path)
        warnings: list[str] = []
        tables: list[TableBlock] = []
        seen: set[tuple] = set()

        for flavor in ("lattice", "stream"):
            try:
                extracted = camelot.read_pdf(str(pdf_path), pages="all", flavor=flavor)
            except Exception as exc:
                warnings.append(f"Camelot {flavor} extraction failed: {exc}")
                continue

            for table in extracted:
                table_block = self._to_table_block(table, flavor)
                if table_block is None:
                    continue

                dedupe_key = self._table_key(table_block)
                if dedupe_key in seen:
                    continue

                seen.add(dedupe_key)
                tables.append(table_block)

        return ParsedDocument(
            source_path=str(pdf_path),
            page_count=page_count,
            tables=tables,
            warnings=warnings,
        )

    def _get_page_count(self, pdf_path: Path) -> int:
        with fitz.open(pdf_path) as document:
            return document.page_count

    def _to_table_block(self, table: object, flavor: str) -> TableBlock | None:
        page = self._coerce_page(getattr(table, "page", 1))
        bbox = self._coerce_bbox(getattr(table, "_bbox", None))
        dataframe = getattr(table, "df", None)
        if dataframe is None or dataframe.empty:
            return None

        confidence = self._coerce_confidence(getattr(table, "accuracy", None))
        evidence = Evidence(
            page=page,
            bbox=bbox,
            method=flavor,
            parser=self.name,
            confidence=confidence,
        )

        raw_cells = getattr(table, "cells", None)
        cells: list[TableCell] = []
        for row_idx, row in enumerate(dataframe.itertuples(index=False, name=None)):
            for col_idx, value in enumerate(row):
                text = "" if value is None else str(value).strip()
                cell_evidence = self._cell_evidence(
                    raw_cells=raw_cells,
                    row=row_idx,
                    col=col_idx,
                    page=page,
                    flavor=flavor,
                    default_bbox=bbox,
                    confidence=confidence,
                )
                cells.append(
                    TableCell(
                        text=text,
                        row=row_idx,
                        col=col_idx,
                        evidence=cell_evidence,
                    )
                )

        return TableBlock(
            page=page,
            cells=cells,
            evidence=evidence,
            confidence=confidence,
        )

    def _cell_evidence(
        self,
        raw_cells: object,
        row: int,
        col: int,
        page: int,
        flavor: str,
        default_bbox: BBox | None,
        confidence: float | None,
    ) -> Evidence | None:
        bbox = default_bbox

        try:
            if raw_cells is not None:
                raw_cell = raw_cells[row][col]
                cell_bbox = self._coerce_bbox(
                    (
                        getattr(raw_cell, "x1", None),
                        getattr(raw_cell, "y1", None),
                        getattr(raw_cell, "x2", None),
                        getattr(raw_cell, "y2", None),
                    )
                )
                if cell_bbox is not None:
                    bbox = cell_bbox
        except (IndexError, TypeError):
            pass

        return Evidence(
            page=page,
            bbox=bbox,
            method=flavor,
            parser=self.name,
            confidence=confidence,
        )

    def _coerce_page(self, value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            first = value.split(",")[0].strip()
            return int(first) if first else 1
        return 1

    def _coerce_bbox(self, value: object) -> BBox | None:
        if not isinstance(value, (tuple, list)) or len(value) != 4:
            return None

        x0, y0, x1, y1 = value
        coords = (x0, y0, x1, y1)
        if any(coord is None for coord in coords):
            return None

        x0f, y0f, x1f, y1f = (float(coord) for coord in coords)
        left, right = sorted((x0f, x1f))
        bottom, top = sorted((y0f, y1f))
        return BBox(x0=left, y0=bottom, x1=right, y1=top)

    def _coerce_confidence(self, value: object) -> float | None:
        if value is None:
            return None

        score = float(value)
        if score > 1.0:
            score /= 100.0

        return max(0.0, min(score, 1.0))

    def _table_key(self, table: TableBlock) -> tuple:
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
