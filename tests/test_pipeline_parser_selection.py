from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pdf_json_parser.cli.app import _load_enabled_parsers_from_config, _resolve_enabled_parsers
from pdf_json_parser.core.pipeline import PdfJsonPipeline
from pdf_json_parser.models.document import ParsedDocument, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence


def _text_block(text: str, parser: str) -> TextBlock:
    return TextBlock(
        text=text,
        evidence=Evidence(
            page=1,
            bbox=BBox(x0=0, y0=0, x1=100, y1=20),
            method="native_pdf_text",
            parser=parser,
            confidence=1.0,
        ),
    )


def test_pipeline_can_be_limited_to_specific_parsers() -> None:
    pipeline = PdfJsonPipeline(enabled_parsers={"pymupdf", "surya"})

    assert pipeline.docling is None
    assert [parser.name for parser in pipeline.digital_parsers] == ["pymupdf"]
    assert [parser.name for parser in pipeline.ocr_parsers] == ["surya"]


def test_pipeline_rejects_unknown_parser_names() -> None:
    with pytest.raises(ValueError, match="Unknown parser selection"):
        PdfJsonPipeline(enabled_parsers={"pymupdf", "madeup"})


def test_pipeline_only_runs_selected_parser_subset(monkeypatch, tmp_path: Path) -> None:
    pipeline = PdfJsonPipeline(enabled_parsers={"pdfplumber"})
    parse_calls = {"docling": 0, "pymupdf": 0, "pdfplumber": 0, "camelot": 0, "ocr": 0}

    pipeline.docling = SimpleNamespace(
        parse=lambda _pdf_path: parse_calls.__setitem__("docling", parse_calls["docling"] + 1),
        name="docling",
    )
    pipeline.digital_parsers = [
        SimpleNamespace(
            parse=lambda _pdf_path: (
                parse_calls.__setitem__("pdfplumber", parse_calls["pdfplumber"] + 1)
                or ParsedDocument(
                    source_path=str(tmp_path / "sample.pdf"),
                    page_count=1,
                    text_blocks=[_text_block("hello", parser="pdfplumber")],
                )
            ),
            name="pdfplumber",
        )
    ]
    pipeline.ocr_parsers = [
        SimpleNamespace(
            parse=lambda _pdf_path: parse_calls.__setitem__("ocr", parse_calls["ocr"] + 1),
            name="paddleocr",
        )
    ]

    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.merge_documents",
        lambda candidates: candidates[0],
    )
    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.extract_schema_json",
        lambda document, _schema_path: {"text": [block.text for block in document.text_blocks]},
    )
    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.validate_extracted_json",
        lambda _extracted, _schema_path: [],
    )
    monkeypatch.setattr("pdf_json_parser.core.pipeline.score_result", lambda _result: 1.0)
    monkeypatch.setattr(pipeline, "_needs_ocr", lambda _document: False)

    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    result = pipeline.run(tmp_path / "sample.pdf", schema_path)

    assert parse_calls == {"docling": 0, "pymupdf": 0, "pdfplumber": 1, "camelot": 0, "ocr": 0}
    assert result.document.text_blocks[0].evidence.parser == "pdfplumber"


def test_load_enabled_parsers_from_config(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        """
pipeline:
  parsers:
    docling:
      enabled: false
    digital:
      enabled: true
      engines:
        pymupdf: true
        pdfplumber: false
        camelot: true
    ocr:
      enabled: true
      engines:
        surya: true
        paddleocr: false
""",
        encoding="utf-8",
    )

    assert _load_enabled_parsers_from_config(config_path) == {"pymupdf", "camelot", "surya"}


def test_resolve_enabled_parsers_prefers_explicit_parser_option(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        """
pipeline:
  parsers:
    selected:
      - camelot
""",
        encoding="utf-8",
    )

    assert _resolve_enabled_parsers(["pymupdf,surya", "pdfplumber"], config_path) == {
        "pymupdf",
        "surya",
        "pdfplumber",
    }
