from __future__ import annotations

import os
import re
from pathlib import Path

import fitz
from PIL import Image
import yaml

from pdf_json_parser.models.document import ImageBlock, ParsedDocument, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.parsers.base import BaseParser


class SuryaParser(BaseParser):
    name = "surya"

    def parse(self, pdf_path: Path) -> ParsedDocument:
        return ParsedDocument(
            source_path=str(pdf_path),
            page_count=0,
            warnings=["Surya OCR only runs against detected image regions"],
        )

    def parse_image_regions(
        self,
        pdf_path: Path,
        image_regions: list[ImageBlock],
        page_count: int,
    ) -> ParsedDocument:
        parsed = ParsedDocument(
            source_path=str(pdf_path),
            page_count=page_count,
        )

        if not image_regions:
            return parsed

        try:
            _, recognition_predictor = self._load_predictor()
        except Exception as exc:
            parsed.warnings.append(f"Surya OCR unavailable: {exc}")
            return parsed

        with fitz.open(pdf_path) as document:
            for region in image_regions:
                bbox = region.evidence.bbox
                if bbox is None:
                    parsed.warnings.append(
                        f"Surya skipped image region on page {region.evidence.page} without bbox"
                    )
                    continue

                try:
                    crop = self._render_region(document, region.evidence.page, bbox)
                    predictions = recognition_predictor([crop])
                except Exception as exc:
                    parsed.warnings.append(
                        f"Surya OCR failed on page {region.evidence.page} image region: {exc}"
                    )
                    continue

                parsed.text_blocks.extend(
                    self._text_blocks_from_prediction(region.evidence.page, bbox, predictions)
                )

        return parsed

    def _load_predictor(self):
        self._apply_runtime_settings()

        from surya.inference import SuryaInferenceManager
        from surya.recognition import RecognitionPredictor

        manager = SuryaInferenceManager()
        return manager, RecognitionPredictor(manager)

    def _apply_runtime_settings(self) -> None:
        runtime_settings = self._load_runtime_settings()
        self._set_default_env(
            "SURYA_INFERENCE_BACKEND",
            runtime_settings.get("backend"),
        )
        self._set_default_env(
            "SURYA_INFERENCE_URL",
            runtime_settings.get("inference_url"),
        )

    def _load_runtime_settings(self) -> dict[str, str]:
        config_path = self._config_path()
        if not config_path.exists():
            return {}

        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        ocr_settings = data.get("ocr") or {}
        surya_settings = ocr_settings.get("surya") or {}
        return surya_settings if isinstance(surya_settings, dict) else {}

    def _config_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / "configs" / "models.yaml"

    def _set_default_env(self, key: str, value: object) -> None:
        if key in os.environ or value in (None, ""):
            return

        os.environ[key] = str(value)

    def _render_region(self, document: fitz.Document, page_number: int, bbox: BBox) -> Image.Image:
        page = document.load_page(page_number - 1)
        rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        pixmap = page.get_pixmap(clip=rect)
        mode = "RGBA" if pixmap.alpha else "RGB"
        return Image.frombytes(mode, [pixmap.width, pixmap.height], pixmap.samples)

    def _text_blocks_from_prediction(
        self,
        page_number: int,
        region_bbox: BBox,
        predictions: list[object],
    ) -> list[TextBlock]:
        if not predictions:
            return []

        page_prediction = predictions[0]
        blocks = getattr(page_prediction, "blocks", None)
        if blocks is None and isinstance(page_prediction, dict):
            blocks = page_prediction.get("blocks", [])

        text_blocks: list[TextBlock] = []
        for block in blocks or []:
            text = self._extract_text(block)
            if not text:
                continue

            bbox = self._extract_bbox(block)
            absolute_bbox = self._offset_bbox(region_bbox, bbox) if bbox is not None else None

            label = self._extract_label(block)
            text_blocks.append(
                TextBlock(
                    text=text,
                    kind=label,
                    evidence=Evidence(
                        page=page_number,
                        bbox=absolute_bbox,
                        method="ocr_image_region",
                        parser=self.name,
                        confidence=self._extract_confidence(block),
                    ),
                )
            )

        return text_blocks

    def _extract_text(self, block: object) -> str:
        html = self._get_attr(block, "html")
        if isinstance(html, str) and html.strip():
            text = re.sub(r"<[^>]+>", " ", html)
            return " ".join(text.split()).strip()

        text = self._get_attr(block, "text")
        if isinstance(text, str):
            return " ".join(text.split()).strip()

        return ""

    def _extract_label(self, block: object) -> str:
        label = self._get_attr(block, "label")
        if not isinstance(label, str):
            return "paragraph"

        normalized = label.strip().lower()
        if normalized in {"text", "sectionheader", "caption", "listgroup"}:
            return "paragraph"
        return normalized or "paragraph"

    def _extract_bbox(self, block: object) -> BBox | None:
        raw_bbox = self._get_attr(block, "bbox")
        if not raw_bbox or len(raw_bbox) != 4:
            return None

        x0, y0, x1, y1 = raw_bbox
        return BBox(x0=x0, y0=y0, x1=x1, y1=y1)

    def _extract_confidence(self, block: object) -> float | None:
        confidence = self._get_attr(block, "confidence")
        return confidence if isinstance(confidence, (float, int)) else None

    def _offset_bbox(self, region_bbox: BBox, local_bbox: BBox | None) -> BBox | None:
        if local_bbox is None:
            return None

        return BBox(
            x0=region_bbox.x0 + local_bbox.x0,
            y0=region_bbox.y0 + local_bbox.y0,
            x1=region_bbox.x0 + local_bbox.x1,
            y1=region_bbox.y0 + local_bbox.y1,
        )

    def _get_attr(self, value: object, key: str) -> object:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)
