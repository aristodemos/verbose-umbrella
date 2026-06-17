from pathlib import Path

import fitz
from PIL import Image

from pdf_json_parser.parsers.pymupdf_parser import PyMuPDFParser


def _build_pdf_with_text_and_image(pdf_path: Path, image_path: Path) -> None:
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Hello from PyMuPDF")
        page.insert_image(fitz.Rect(72, 120, 172, 220), filename=str(image_path))
        doc.save(pdf_path)


def test_pymupdf_parser_extracts_text_blocks_and_images(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    pdf_path = tmp_path / "sample.pdf"

    Image.new("RGB", (20, 20), color=(255, 0, 0)).save(image_path)
    _build_pdf_with_text_and_image(pdf_path, image_path)

    parsed = PyMuPDFParser().parse(pdf_path)

    assert parsed.page_count == 1
    assert len(parsed.text_blocks) == 1
    assert parsed.text_blocks[0].text == "Hello from PyMuPDF"
    assert parsed.text_blocks[0].evidence.page == 1

    assert len(parsed.image_blocks) == 1
    assert parsed.image_blocks[0].evidence.page == 1
    assert parsed.image_blocks[0].evidence.bbox is not None
    assert parsed.image_blocks[0].width == 20
    assert parsed.image_blocks[0].height == 20

    assert parsed.warnings == ["Embedded image objects detected on page 1: 1"]


def test_pymupdf_parser_tracks_image_only_pages(tmp_path: Path) -> None:
    image_path = tmp_path / "image_only.png"
    pdf_path = tmp_path / "image_only.pdf"

    Image.new("RGB", (32, 16), color=(0, 255, 0)).save(image_path)

    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_image(fitz.Rect(40, 40, 140, 90), filename=str(image_path))
        doc.save(pdf_path)

    parsed = PyMuPDFParser().parse(pdf_path)

    assert parsed.text_blocks == []
    assert len(parsed.image_blocks) == 1
    assert parsed.image_blocks[0].width == 32
    assert parsed.image_blocks[0].height == 16
    assert parsed.image_blocks[0].evidence.bbox is not None
