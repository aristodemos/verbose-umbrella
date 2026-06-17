from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from pdf_json_parser.models.document import ParsedDocument, TableBlock, TableCell, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.base import BaseParser


class DoclingParser(BaseParser):
    name = "docling"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        page_count = self._get_page_count(pdf_path)

        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            return ParsedDocument(
                source_path=str(pdf_path),
                language="el",
                page_count=page_count,
                warnings=["Docling dependency is not installed; skipping Docling parsing."],
            )

        conversion = DocumentConverter().convert(str(pdf_path))
        document = getattr(conversion, "document", conversion)

        parsed = ParsedDocument(
            source_path=str(pdf_path),
            language="el",
            page_count=self._page_count_from_document(document) or page_count,
        )

        for item in self._iter_items(document):
            if self._is_table_item(item):
                table = self._to_table_block(item)
                if table is not None:
                    parsed.tables.append(table)
                continue

            text = self._extract_text(item)
            if not text:
                continue

            parsed.text_blocks.append(
                TextBlock(
                    text=text,
                    evidence=Evidence(
                        page=self._item_page(item),
                        bbox=self._item_bbox(item),
                        method="structured_layout",
                        parser=self.name,
                        confidence=self._item_confidence(item),
                    ),
                )
            )

        if not parsed.text_blocks and not parsed.tables:
            parsed.warnings.append(
                "Docling conversion completed but no supported text or table blocks were extracted."
            )

        return parsed

    def _get_page_count(self, pdf_path: Path) -> int:
        with fitz.open(pdf_path) as document:
            return document.page_count

    def _page_count_from_document(self, document: Any) -> int | None:
        pages = getattr(document, "pages", None)
        if pages is None:
            return None

        try:
            return len(pages)
        except TypeError:
            return None

    def _iter_items(self, document: Any) -> list[Any]:
        if hasattr(document, "iterate_items"):
            items: list[Any] = []
            for entry in document.iterate_items():
                if isinstance(entry, tuple):
                    items.append(entry[0])
                else:
                    items.append(entry)
            return items

        items: list[Any] = []
        for attr_name in ("texts", "tables", "items"):
            value = getattr(document, attr_name, None)
            if value is None:
                continue
            items.extend(list(value))
        return items

    def _is_table_item(self, item: Any) -> bool:
        class_name = item.__class__.__name__.lower()
        if "table" in class_name:
            return True

        return any(
            hasattr(item, attr_name)
            for attr_name in ("data", "table_cells", "export_to_dataframe")
        )

    def _extract_text(self, item: Any) -> str:
        for attr_name in ("text", "orig", "orig_text"):
            value = getattr(item, attr_name, None)
            if value:
                return str(value).strip()

        export_to_text = getattr(item, "export_to_text", None)
        if callable(export_to_text):
            value = export_to_text()
            if value:
                return str(value).strip()

        return ""

    def _to_table_block(self, item: Any) -> TableBlock | None:
        page = self._item_page(item)
        bbox = self._item_bbox(item)
        confidence = self._item_confidence(item)

        evidence = Evidence(
            page=page,
            bbox=bbox,
            method="structured_table",
            parser=self.name,
            confidence=confidence,
        )

        cells = self._table_cells_from_dataframe(item, page, bbox, confidence)
        if not cells:
            cells = self._table_cells_from_raw_cells(item, page, bbox, confidence)
        if not cells:
            return None

        title = self._string_or_none(getattr(item, "caption_text", None))
        if title is None:
            title = self._string_or_none(getattr(item, "label", None))

        return TableBlock(
            title=title,
            page=page,
            cells=cells,
            evidence=evidence,
            confidence=confidence,
        )

    def _table_cells_from_dataframe(
        self,
        item: Any,
        page: int,
        default_bbox: BBox | None,
        confidence: float | None,
    ) -> list[TableCell]:
        export_to_dataframe = getattr(item, "export_to_dataframe", None)
        if not callable(export_to_dataframe):
            return []

        dataframe = export_to_dataframe()
        if dataframe is None or getattr(dataframe, "empty", False):
            return []

        raw_cells = self._raw_table_cells(item)
        cells: list[TableCell] = []
        for row_idx, row in enumerate(dataframe.itertuples(index=False, name=None)):
            for col_idx, value in enumerate(row):
                cell_item = self._lookup_raw_cell(raw_cells, row_idx, col_idx)
                cell_bbox = self._bbox_from_cell(cell_item) or default_bbox
                cells.append(
                    TableCell(
                        text="" if value is None else str(value).strip(),
                        row=row_idx,
                        col=col_idx,
                        evidence=Evidence(
                            page=page,
                            bbox=cell_bbox,
                            method="structured_table",
                            parser=self.name,
                            confidence=confidence,
                        ),
                    )
                )
        return cells

    def _table_cells_from_raw_cells(
        self,
        item: Any,
        page: int,
        default_bbox: BBox | None,
        confidence: float | None,
    ) -> list[TableCell]:
        raw_cells = self._raw_table_cells(item)
        if not raw_cells:
            return []

        cells: list[TableCell] = []
        for raw_cell in raw_cells:
            row = self._first_int(raw_cell, "row", "row_idx", "row_index", default=0)
            col = self._first_int(raw_cell, "col", "col_idx", "col_index", default=0)
            text = self._string_or_none(self._first_attr(raw_cell, "text", "value")) or ""
            cells.append(
                TableCell(
                    text=text,
                    row=row,
                    col=col,
                    evidence=Evidence(
                        page=page,
                        bbox=self._bbox_from_cell(raw_cell) or default_bbox,
                        method="structured_table",
                        parser=self.name,
                        confidence=confidence,
                    ),
                )
            )
        return cells

    def _raw_table_cells(self, item: Any) -> list[Any]:
        raw_cells = getattr(item, "table_cells", None)
        if raw_cells is None:
            data = getattr(item, "data", None)
            raw_cells = getattr(data, "table_cells", None)
        if raw_cells is None:
            return []
        return list(raw_cells)

    def _lookup_raw_cell(self, raw_cells: list[Any], row: int, col: int) -> Any | None:
        for raw_cell in raw_cells:
            raw_row = self._first_int(raw_cell, "row", "row_idx", "row_index", default=-1)
            raw_col = self._first_int(raw_cell, "col", "col_idx", "col_index", default=-1)
            if raw_row == row and raw_col == col:
                return raw_cell
        return None

    def _item_page(self, item: Any) -> int:
        provenance = self._item_provenance(item)
        for source in provenance:
            value = self._first_attr(source, "page_no", "page", "page_num")
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return 1

    def _item_bbox(self, item: Any) -> BBox | None:
        provenance = self._item_provenance(item)
        for source in provenance:
            bbox = self._coerce_bbox(self._first_attr(source, "bbox", "box"))
            if bbox is not None:
                return bbox
        return self._coerce_bbox(getattr(item, "bbox", None))

    def _item_confidence(self, item: Any) -> float | None:
        confidence = self._coerce_confidence(getattr(item, "confidence", None))
        if confidence is not None:
            return confidence

        for source in self._item_provenance(item):
            confidence = self._coerce_confidence(getattr(source, "confidence", None))
            if confidence is not None:
                return confidence
        return None

    def _item_provenance(self, item: Any) -> list[Any]:
        for attr_name in ("prov", "provenance", "provs"):
            value = getattr(item, attr_name, None)
            if value:
                return list(value)
        return []

    def _bbox_from_cell(self, cell: Any) -> BBox | None:
        if cell is None:
            return None

        for attr_name in ("bbox", "box"):
            bbox = self._coerce_bbox(getattr(cell, attr_name, None))
            if bbox is not None:
                return bbox
        return None

    def _coerce_bbox(self, value: Any) -> BBox | None:
        if value is None:
            return None

        if isinstance(value, (tuple, list)) and len(value) == 4:
            coords = value
        else:
            coords = None
            for attr_names in (
                ("x0", "y0", "x1", "y1"),
                ("l", "t", "r", "b"),
                ("left", "top", "right", "bottom"),
            ):
                extracted = [getattr(value, attr_name, None) for attr_name in attr_names]
                if all(coord is not None for coord in extracted):
                    coords = extracted
                    break

        if coords is None or any(coord is None for coord in coords):
            return None

        x0, y0, x1, y1 = (float(coord) for coord in coords)
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))
        return BBox(x0=left, y0=top, x1=right, y1=bottom)

    def _coerce_confidence(self, value: Any) -> float | None:
        if value is None:
            return None

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None

        if confidence > 1.0:
            confidence /= 100.0

        return max(0.0, min(confidence, 1.0))

    def _first_attr(self, value: Any, *attr_names: str) -> Any:
        for attr_name in attr_names:
            if hasattr(value, attr_name):
                return getattr(value, attr_name)
        return None

    def _first_int(self, value: Any, *attr_names: str, default: int) -> int:
        raw_value = self._first_attr(value, *attr_names)
        if raw_value is None:
            return default

        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return default

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None
