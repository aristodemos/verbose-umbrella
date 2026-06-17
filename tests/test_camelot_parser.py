from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from pdf_json_parser.parsers.camelot_parser import CamelotParser


class _FakeDoc:
    def __init__(self, page_count: int) -> None:
        self.page_count = page_count

    def __enter__(self) -> _FakeDoc:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_camelot_parser_extracts_tables_and_deduplicates(monkeypatch) -> None:
    parser = CamelotParser()
    pdf_path = Path("sample.pdf")

    cell = SimpleNamespace(x1=10, y1=20, x2=30, y2=40)
    dataframe = pd.DataFrame([["Header", "Value"], ["A", "1"]])

    lattice_table = SimpleNamespace(
        page="1",
        _bbox=(5, 15, 35, 45),
        df=dataframe,
        cells=[[cell, cell], [cell, cell]],
        accuracy=98,
    )
    stream_table = SimpleNamespace(
        page="1",
        _bbox=(5, 15, 35, 45),
        df=dataframe,
        cells=[[cell, cell], [cell, cell]],
        accuracy=91,
    )

    fake_camelot = SimpleNamespace(
        read_pdf=lambda path, pages, flavor: [lattice_table] if flavor == "lattice" else [stream_table]
    )

    monkeypatch.setattr("pdf_json_parser.parsers.camelot_parser.fitz.open", lambda _: _FakeDoc(3))
    monkeypatch.setitem(sys.modules, "camelot", fake_camelot)

    document = parser.parse(pdf_path)

    assert document.page_count == 3
    assert document.warnings == []
    assert len(document.tables) == 1

    table = document.tables[0]
    assert table.page == 1
    assert table.confidence == 0.98
    assert table.evidence.method == "lattice"
    assert table.evidence.bbox is not None
    assert len(table.cells) == 4
    assert table.cells[0].text == "Header"
    assert table.cells[0].evidence is not None
    assert table.cells[0].evidence.bbox is not None
    assert table.cells[0].evidence.bbox.x0 == 10
    assert table.cells[0].evidence.bbox.y0 == 20


def test_camelot_parser_collects_flavor_failures(monkeypatch) -> None:
    parser = CamelotParser()
    pdf_path = Path("sample.pdf")

    dataframe = pd.DataFrame([["A"]])
    working_table = SimpleNamespace(
        page=2,
        _bbox=(1, 2, 3, 4),
        df=dataframe,
        cells=[[SimpleNamespace(x1=1, y1=2, x2=3, y2=4)]],
        accuracy=87,
    )

    def fake_read_pdf(path, pages, flavor):
        if flavor == "lattice":
            raise RuntimeError("ghostscript missing")
        return [working_table]

    fake_camelot = SimpleNamespace(read_pdf=fake_read_pdf)

    monkeypatch.setattr("pdf_json_parser.parsers.camelot_parser.fitz.open", lambda _: _FakeDoc(4))
    monkeypatch.setitem(sys.modules, "camelot", fake_camelot)

    document = parser.parse(pdf_path)

    assert document.page_count == 4
    assert len(document.tables) == 1
    assert len(document.warnings) == 1
    assert "lattice" in document.warnings[0].lower()
    assert "ghostscript missing" in document.warnings[0].lower()
