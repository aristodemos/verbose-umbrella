from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import fitz
from PIL import Image

from pdf_json_parser.models.document import ImageBlock, ParsedDocument, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.pymupdf_parser import PyMuPDFParser
from pdf_json_parser.parsers.surya_parser import SuryaParser

SURYA_TEST_INFERENCE_URL = "http://127.0.0.1:8000/v1"
SURYA_TEST_OVERRIDE_URL = "http://127.0.0.1:8001/v1"


def _build_pdf_with_embedded_image(pdf_path: Path, image_path: Path) -> None:
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_image(fitz.Rect(72, 120, 172, 220), filename=str(image_path))
        doc.save(pdf_path)


def test_surya_parser_ocrs_detected_image_regions_only(monkeypatch, tmp_path: Path) -> None:
    package = types.ModuleType("surya")
    package.__path__ = []

    inference_module = types.ModuleType("surya.inference")
    recognition_module = types.ModuleType("surya.recognition")

    class FakeSuryaInferenceManager:
        pass

    class FakeRecognitionPredictor:
        def __init__(self, manager) -> None:
            self.manager = manager

        def __call__(self, images):
            assert len(images) == 1
            assert images[0].size == (100, 100)
            return [
                SimpleNamespace(
                    blocks=[
                        SimpleNamespace(
                            html="<p>Image OCR text</p>",
                            label="Text",
                            bbox=[10, 15, 70, 35],
                            confidence=0.91,
                        )
                    ]
                )
            ]

    inference_module.SuryaInferenceManager = FakeSuryaInferenceManager
    recognition_module.RecognitionPredictor = FakeRecognitionPredictor

    monkeypatch.setitem(sys.modules, "surya", package)
    monkeypatch.setitem(sys.modules, "surya.inference", inference_module)
    monkeypatch.setitem(sys.modules, "surya.recognition", recognition_module)

    image_path = tmp_path / "image.png"
    pdf_path = tmp_path / "sample.pdf"
    Image.new("RGB", (20, 20), color=(255, 0, 0)).save(image_path)
    _build_pdf_with_embedded_image(pdf_path, image_path)

    base_document = PyMuPDFParser().parse(pdf_path)

    parsed = SuryaParser().parse_image_regions(
        pdf_path,
        base_document.image_blocks,
        base_document.page_count,
    )

    assert parsed.page_count == 1
    assert parsed.image_blocks == []
    assert parsed.warnings == []
    assert len(parsed.text_blocks) == 1

    block = parsed.text_blocks[0]
    assert block.text == "Image OCR text"
    assert block.kind == "paragraph"
    assert block.evidence.page == 1
    assert block.evidence.method == "ocr_image_region"
    assert block.evidence.confidence == 0.91
    assert block.evidence.bbox is not None
    assert block.evidence.bbox.x0 == 82
    assert block.evidence.bbox.y0 == 135
    assert block.evidence.bbox.x1 == 142
    assert block.evidence.bbox.y1 == 155


def test_surya_parser_reports_missing_dependency_for_image_regions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    parser = SuryaParser()
    monkeypatch.setattr(
        parser,
        "_load_predictor",
        lambda: (_ for _ in ()).throw(ImportError("surya not installed")),
    )
    document = parser.parse_image_regions(
        tmp_path / "sample.pdf",
        [
            ImageBlock(
                evidence=Evidence(
                    page=1,
                    bbox=BBox(x0=0, y0=0, x1=10, y1=10),
                    method="embedded_image_object",
                    parser="test",
                    confidence=1.0,
                )
            )
        ],
        page_count=1,
    )

    assert document.text_blocks == []
    assert len(document.warnings) == 1
    assert "Surya OCR unavailable" in document.warnings[0]


def test_surya_parser_applies_runtime_settings_from_models_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
ocr:
  surya:
    backend: "llamacpp"
    inference_url: "%s"
""" % SURYA_TEST_INFERENCE_URL,
        encoding="utf-8",
    )

    parser = SuryaParser()
    monkeypatch.setattr(parser, "_config_path", lambda: config_path)
    monkeypatch.delenv("SURYA_INFERENCE_BACKEND", raising=False)
    monkeypatch.delenv("SURYA_INFERENCE_URL", raising=False)

    parser._apply_runtime_settings()

    assert os.environ["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert os.environ["SURYA_INFERENCE_URL"] == SURYA_TEST_INFERENCE_URL


def test_surya_parser_runtime_settings_do_not_override_existing_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
ocr:
  surya:
    backend: "vllm"
    inference_url: "%s"
""" % SURYA_TEST_OVERRIDE_URL,
        encoding="utf-8",
    )

    parser = SuryaParser()
    monkeypatch.setattr(parser, "_config_path", lambda: config_path)
    monkeypatch.setenv("SURYA_INFERENCE_BACKEND", "llamacpp")
    monkeypatch.setenv("SURYA_INFERENCE_URL", SURYA_TEST_INFERENCE_URL)

    parser._apply_runtime_settings()

    assert os.environ["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert os.environ["SURYA_INFERENCE_URL"] == SURYA_TEST_INFERENCE_URL


def test_pipeline_calls_surya_only_for_image_regions(monkeypatch, tmp_path: Path) -> None:
    from pdf_json_parser.core.pipeline import PdfJsonPipeline

    pipeline = PdfJsonPipeline()
    image_region = ImageBlock(
        evidence=Evidence(
            page=1,
            bbox=BBox(x0=10, y0=20, x1=30, y1=40),
            method="embedded_image_object",
            parser="pymupdf",
            confidence=1.0,
        )
    )
    merged_document = ParsedDocument(
        source_path=str(tmp_path / "sample.pdf"),
        page_count=1,
        image_blocks=[image_region],
    )
    surya_output = ParsedDocument(
        source_path=str(tmp_path / "sample.pdf"),
        page_count=1,
        text_blocks=[
            TextBlock(
                text="region ocr",
                evidence=Evidence(
                    page=1,
                    bbox=BBox(x0=10, y0=20, x1=30, y1=40),
                    method="ocr_image_region",
                    parser="surya",
                    confidence=0.8,
                ),
            )
        ],
    )

    pipeline.docling = SimpleNamespace(
        parse=lambda _pdf_path: ParsedDocument(source_path="docling", page_count=1),
        name="docling",
    )
    pipeline.digital_parsers = [
        SimpleNamespace(parse=lambda _pdf_path: merged_document, name="digital")
    ]

    parse_calls = {"paddle": 0, "surya_parse": 0, "surya_regions": 0}

    class FakePaddleParser:
        name = "paddleocr"

        def parse(self, _pdf_path: Path) -> ParsedDocument:
            parse_calls["paddle"] += 1
            return ParsedDocument(source_path=str(tmp_path / "sample.pdf"), page_count=1)

    class FakeSuryaParser:
        name = "surya"

        def parse(self, _pdf_path: Path) -> ParsedDocument:
            parse_calls["surya_parse"] += 1
            raise AssertionError("pipeline should not call Surya.parse for whole documents")

        def parse_image_regions(
            self,
            _pdf_path: Path,
            image_regions: list[ImageBlock],
            page_count: int,
        ) -> ParsedDocument:
            parse_calls["surya_regions"] += 1
            assert image_regions == [image_region]
            assert page_count == 1
            return surya_output

    pipeline.ocr_parsers = [FakePaddleParser(), FakeSuryaParser()]

    monkeypatch.setattr(
        "pdf_json_parser.core.pipeline.merge_documents",
        lambda candidates: candidates[-1] if len(candidates) > 1 else candidates[0],
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
    monkeypatch.setattr(pipeline, "_needs_ocr", lambda _document: True)

    schema_path = tmp_path / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")

    result = pipeline.run(tmp_path / "sample.pdf", schema_path)

    assert parse_calls == {"paddle": 1, "surya_parse": 0, "surya_regions": 1}
    assert result.document.text_blocks[0].text == "region ocr"
