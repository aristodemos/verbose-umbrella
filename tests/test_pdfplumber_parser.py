from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from pdf_json_parser.parsers.pdfplumber_parser import PdfPlumberParser


class _FakePdf:
    def __init__(self, pages) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePdf:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeRenderableImage:
    def __init__(self) -> None:
        self.rects: list[tuple[float, float, float, float]] = []

    def draw_rect(self, rect, stroke=None, stroke_width=None) -> None:
        self.rects.append(tuple(rect))

    def save(self, path: Path) -> None:
        Path(path).write_text("debug", encoding="utf-8")


class _FakePage:
    def __init__(self, *, words, tables_by_strategy, images=None) -> None:
        self._words = words
        self._tables_by_strategy = tables_by_strategy
        self.images = images or []
        self.rendered_images: list[_FakeRenderableImage] = []

    def extract_words(self):
        return self._words

    def find_tables(self, table_settings):
        strategy = (
            table_settings.get("vertical_strategy"),
            table_settings.get("horizontal_strategy"),
        )
        return self._tables_by_strategy.get(strategy, [])

    def to_image(self, resolution):
        image = _FakeRenderableImage()
        self.rendered_images.append(image)
        return image


def test_pdfplumber_parser_uses_text_table_fallback_and_exports_debug_images(
    monkeypatch,
    tmp_path: Path,
) -> None:
    table = SimpleNamespace(
        bbox=(10, 20, 90, 80),
        rows=[
            SimpleNamespace(cells=[(10, 20, 40, 40), (40, 20, 90, 40)]),
            SimpleNamespace(cells=[(10, 40, 40, 80), (40, 40, 90, 80)]),
        ],
        extract=lambda: [["Header", "Value"], ["A", "1"]],
    )
    page = _FakePage(
        words=[
            {"text": "Invoice", "x0": 5, "x1": 45, "top": 4, "bottom": 14},
            {"text": "123", "x0": 50, "x1": 68, "top": 4, "bottom": 14},
        ],
        tables_by_strategy={
            ("lines", "lines"): [],
            ("text", "text"): [table],
        },
        images=[{"name": "embedded"}],
    )

    fake_pdfplumber = SimpleNamespace(open=lambda _: _FakePdf([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    parser = PdfPlumberParser(debug_output_dir=tmp_path / "debug")
    document = parser.parse(Path("sample.pdf"))

    assert document.page_count == 1
    assert len(document.text_blocks) == 1
    assert document.text_blocks[0].text == "Invoice 123"

    assert len(document.tables) == 1
    assert document.tables[0].confidence == 0.75
    assert document.tables[0].evidence.method == "text"
    assert len(document.tables[0].cells) == 4
    assert document.tables[0].cells[0].evidence is not None
    assert document.tables[0].cells[0].evidence.bbox is not None
    assert document.tables[0].cells[0].evidence.bbox.x0 == 10

    assert "pdfplumber text-based table fallback used on page 1" in document.warnings
    assert "Embedded image objects detected on page 1: 1" in document.warnings
    assert (tmp_path / "debug" / "page-001.png").exists()
    assert (tmp_path / "debug" / "page-001.tables.png").exists()
    assert len(page.rendered_images) == 2
    assert page.rendered_images[1].rects == [(10.0, 20.0, 90.0, 80.0)]


def test_pdfplumber_parser_prefers_line_tables_and_deduplicates(monkeypatch) -> None:
    line_table = SimpleNamespace(
        bbox=(5, 10, 45, 30),
        rows=[SimpleNamespace(cells=[(5, 10, 25, 20), (25, 10, 45, 20)])],
        extract=lambda: [["A", "B"]],
    )
    duplicate_text_table = SimpleNamespace(
        bbox=(5, 10, 45, 30),
        rows=[SimpleNamespace(cells=[(5, 10, 25, 20), (25, 10, 45, 20)])],
        extract=lambda: [["A", "B"]],
    )
    page = _FakePage(
        words=[],
        tables_by_strategy={
            ("lines", "lines"): [line_table],
            ("text", "text"): [duplicate_text_table],
        },
    )

    fake_pdfplumber = SimpleNamespace(open=lambda _: _FakePdf([page]))
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    document = PdfPlumberParser().parse(Path("sample.pdf"))

    assert len(document.tables) == 1
    assert document.tables[0].confidence == 0.9
    assert document.tables[0].evidence.method == "lines"
    assert document.warnings == []
