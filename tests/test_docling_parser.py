from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import fitz
import pandas as pd

from pdf_json_parser.core.pipeline import PdfJsonPipeline
from pdf_json_parser.models.document import ParsedDocument, TableBlock, TableCell, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.docling_parser import DoclingParser


def _create_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page()
    document.new_page()
    document.save(path)
    document.close()


def _install_fake_docling(monkeypatch, fake_document: object) -> None:
    package = types.ModuleType("docling")
    package.__path__ = []

    converter_module = types.ModuleType("docling.document_converter")

    class FakeDocumentConverter:
        def convert(self, path: str) -> object:
            return SimpleNamespace(document=fake_document)

    converter_module.DocumentConverter = FakeDocumentConverter

    monkeypatch.setitem(sys.modules, "docling", package)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)


def _make_text_block(text: str) -> TextBlock:
    return TextBlock(
        text=text,
        evidence=Evidence(
            page=1,
            bbox=BBox(x0=0, y0=0, x1=100, y1=20),
            method="native_pdf_text",
            parser="test",
            confidence=1.0,
        ),
    )


def _make_table_block() -> TableBlock:
    return TableBlock(
        page=1,
        cells=[
            TableCell(
                text="Header",
                row=0,
                col=0,
                evidence=Evidence(
                    page=1,
                    bbox=BBox(x0=0, y0=20, x1=40, y1=40),
                    method="lines",
                    parser="test",
                    confidence=0.9,
                ),
            )
        ],
        evidence=Evidence(
            page=1,
            bbox=BBox(x0=0, y0=20, x1=100, y1=80),
            method="lines",
            parser="test",
            confidence=0.9,
        ),
        confidence=0.9,
    )


def test_docling_parser_extracts_text_blocks_and_tables(monkeypatch, tmp_path: Path) -> None:
    class FakeBBox:
        def __init__(self, x0: float, y0: float, x1: float, y1: float) -> None:
            self.x0 = x0
            self.y0 = y0
            self.x1 = x1
            self.y1 = y1

    class FakeProv:
        def __init__(self, page_no: int, bbox: FakeBBox, confidence: float) -> None:
            self.page_no = page_no
            self.bbox = bbox
            self.confidence = confidence

    class FakeCell:
        def __init__(self, row_idx: int, col_idx: int, text: str, bbox: FakeBBox) -> None:
            self.row_idx = row_idx
            self.col_idx = col_idx
            self.text = text
            self.bbox = bbox

    class FakeTextItem:
        def __init__(self) -> None:
            self.text = "Hello from Docling"
            self.prov = [FakeProv(1, FakeBBox(10, 10, 80, 24), 0.96)]

    class FakeTableItem:
        label = "Detected table"

        def __init__(self) -> None:
            self.prov = [FakeProv(2, FakeBBox(15, 30, 120, 100), 0.88)]
            self.table_cells = [
                FakeCell(0, 0, "Header", FakeBBox(15, 30, 65, 50)),
                FakeCell(0, 1, "Value", FakeBBox(65, 30, 120, 50)),
                FakeCell(1, 0, "A", FakeBBox(15, 50, 65, 75)),
                FakeCell(1, 1, "1", FakeBBox(65, 50, 120, 75)),
            ]

        def export_to_dataframe(self) -> pd.DataFrame:
            return pd.DataFrame([["Header", "Value"], ["A", "1"]])

    class FakeDocument:
        pages = [object(), object()]

        def iterate_items(self):
            yield FakeTextItem(), 0
            yield FakeTableItem(), 0

    _install_fake_docling(monkeypatch, FakeDocument())

    pdf_path = tmp_path / "sample.pdf"
    _create_pdf(pdf_path)

    parsed = DoclingParser().parse(pdf_path)

    assert parsed.page_count == 2
    assert len(parsed.text_blocks) == 1
    assert parsed.text_blocks[0].text == "Hello from Docling"
    assert parsed.text_blocks[0].evidence.page == 1
    assert parsed.text_blocks[0].evidence.bbox is not None
    assert parsed.text_blocks[0].evidence.bbox.x0 == 10

    assert len(parsed.tables) == 1
    assert parsed.tables[0].page == 2
    assert parsed.tables[0].confidence == 0.88
    assert parsed.tables[0].evidence.bbox is not None
    assert parsed.tables[0].evidence.bbox.x1 == 120
    assert len(parsed.tables[0].cells) == 4
    assert parsed.tables[0].cells[0].text == "Header"
    assert parsed.tables[0].cells[0].evidence is not None
    assert parsed.tables[0].cells[0].evidence.bbox is not None
    assert parsed.tables[0].cells[0].evidence.bbox.x0 == 15
    assert parsed.warnings == []


def test_pipeline_compares_docling_against_deterministic_output(monkeypatch, tmp_path: Path) -> None:
    pipeline = PdfJsonPipeline()

    docling_document = ParsedDocument(
        source_path="docling",
        page_count=1,
        text_blocks=[_make_text_block("Docling text only")],
        tables=[],
        warnings=["Docling parser note"],
    )
    deterministic_document = ParsedDocument(
        source_path="deterministic",
        page_count=1,
        text_blocks=[_make_text_block("Deterministic text only")],
        tables=[_make_table_block()],
    )

    pipeline.docling = SimpleNamespace(parse=lambda _pdf_path: docling_document, name="docling")
    pipeline.digital_parsers = [
        SimpleNamespace(parse=lambda _pdf_path: deterministic_document, name="deterministic")
    ]
    pipeline.ocr_parsers = []

    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.merge_documents",
        lambda candidates: candidates[0],
    )
    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.extract_schema_json",
        lambda document, schema_path: {"text_block_count": len(document.text_blocks)},
    )
    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.validate_extracted_json",
        lambda extracted, schema_path: [],
    )
    monkeypatch.setattr("pdf_json_parser.core.pipeline.score_result", lambda result: 1.0)
    monkeypatch.setattr(pipeline, "_needs_ocr", lambda _document: False)

    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    result = pipeline.run(tmp_path / "ignored.pdf", schema_path)

    assert "docling: Docling parser note" in result.document.warnings
    assert any(
        warning.endswith("Docling comparison against deterministic output: text_blocks=1/1, tables=0/1, line_overlap=0.000")
        for warning in result.document.warnings
    )
    assert any(
        warning.endswith("Docling table count differs from deterministic output (0 vs 1).")
        for warning in result.document.warnings
    )
    assert any("Docling text diverges from deterministic output" in warning for warning in result.document.warnings)


def test_pipeline_normalizes_duplicate_warning_prefixes(monkeypatch, tmp_path: Path) -> None:
    pipeline = PdfJsonPipeline()
    pdf_path = tmp_path / "erb.pdf"
    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    docling_document = ParsedDocument(
        source_path=str(pdf_path),
        page_count=1,
        text_blocks=[_make_text_block("Deterministic text only")],
        tables=[_make_table_block()],
        warnings=[
            f"{pdf_path}: Embedded image objects detected on page 4: 1",
            f"{pdf_path}: Embedded image objects detected on page 4: 1",
            "Docling comparison against deterministic output: text_blocks=98/394, tables=1/41, line_overlap=0.294",
            "Docling text diverges from deterministic output (normalized line overlap 0.294).",
            "Docling table count differs from deterministic output (1 vs 41).",
        ],
    )

    merged_document = ParsedDocument(
        source_path=str(pdf_path),
        page_count=1,
        text_blocks=[_make_text_block("Deterministic text only")],
        tables=[_make_table_block()],
        warnings=list(docling_document.warnings),
    )

    pipeline.docling = SimpleNamespace(parse=lambda _pdf_path: docling_document, name="docling")
    pipeline.digital_parsers = []
    pipeline.ocr_parsers = [SimpleNamespace(parse=lambda _pdf_path: ParsedDocument(source_path=str(pdf_path), page_count=1), name="ocr")]

    merge_calls = {"count": 0}

    def fake_merge(candidates):
        merge_calls["count"] += 1
        return merged_document

    monkeypatch.setattr("pdf_json_parser.core.pipeline.merge_documents", fake_merge)
    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.extract_schema_json",
        lambda document, _schema_path: {"warnings": document.warnings},
    )
    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.validate_extracted_json",
        lambda _extracted, _schema_path: [],
    )
    monkeypatch.setattr("pdf_json_parser.core.pipeline.score_result", lambda _result: 1.0)
    monkeypatch.setattr(pipeline, "_needs_ocr", lambda _document: True)

    result = pipeline.run(pdf_path, schema_path)

    assert merge_calls["count"] == 1
    assert result.document.warnings == [
        f"{pdf_path}: Embedded image objects detected on page 4: 1",
        f"{pdf_path}: Docling comparison against deterministic output: text_blocks=98/394, tables=1/41, line_overlap=0.294",
        f"{pdf_path}: Docling text diverges from deterministic output (normalized line overlap 0.294).",
        f"{pdf_path}: Docling table count differs from deterministic output (1 vs 41).",
    ]
