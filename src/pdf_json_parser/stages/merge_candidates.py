from __future__ import annotations

import math
import re

from pdf_json_parser.models.document import ImageBlock, ParsedDocument, TableBlock, TableCell, TextBlock
from pdf_json_parser.models.geometry import BBox

PARSER_PRIORITY = {
    "pymupdf": 5,
    "pdfplumber": 4,
    "camelot": 4,
    "surya": 3,
    "paddleocr": 2,
    "docling": 1,
}

COORDINATE_TOLERANCE = 3.0
IOU_THRESHOLD = 0.7
TABLE_CONTENT_OVERLAP_THRESHOLD = 0.8


def merge_documents(candidates: list[ParsedDocument]) -> ParsedDocument:
    """
    Merge multiple ParsedDocument instances into a single ParsedDocument.

    The merge keeps deterministic parser routing intact and only deduplicates
    overlapping blocks inside the merged output.
    """
    if not candidates:
        raise ValueError("No candidates provided for merging.")

    best = max(
        candidates,
        key=lambda doc: (
            len(doc.tables),
            sum(len(block.text) for block in doc.text_blocks),
        ),
    )

    merged = ParsedDocument(
        source_path=best.source_path,
        language=best.language,
        page_count=max(doc.page_count for doc in candidates),
    )

    warning_keys: set[str] = set()

    for doc in candidates:
        for block in doc.text_blocks:
            _merge_text_block(merged.text_blocks, block)

        for image in doc.image_blocks:
            _merge_image_block(merged.image_blocks, image)

        for table in doc.tables:
            _merge_table_block(merged.tables, table)

        for warning in doc.warnings:
            prefixed = f"{doc.source_path}: {warning}"
            key = _warning_key(prefixed)
            if key in warning_keys:
                continue
            warning_keys.add(key)
            merged.warnings.append(prefixed.strip())

    return merged


def _merge_text_block(existing: list[TextBlock], candidate: TextBlock) -> None:
    for index, block in enumerate(existing):
        if not _text_blocks_match(block, candidate):
            continue
        existing[index] = _choose_better_text_block(block, candidate)
        return

    existing.append(candidate)


def _merge_table_block(existing: list[TableBlock], candidate: TableBlock) -> None:
    for index, table in enumerate(existing):
        if not _table_blocks_match(table, candidate):
            continue
        existing[index] = _choose_better_table_block(table, candidate)
        return

    existing.append(candidate)


def _merge_image_block(existing: list[ImageBlock], candidate: ImageBlock) -> None:
    for index, image in enumerate(existing):
        if not _image_blocks_match(image, candidate):
            continue
        existing[index] = _merge_image_metadata(image, candidate)
        return

    existing.append(candidate)


def _text_blocks_match(left: TextBlock, right: TextBlock) -> bool:
    if left.evidence.page != right.evidence.page:
        return False

    left_text = _normalize_text(left.text)
    right_text = _normalize_text(right.text)
    if not left_text or left_text != right_text:
        return False

    left_bbox = left.evidence.bbox
    right_bbox = right.evidence.bbox
    if left_bbox is not None and right_bbox is not None:
        return _bbox_similar(left_bbox, right_bbox)

    return True


def _table_blocks_match(left: TableBlock, right: TableBlock) -> bool:
    if left.page != right.page:
        return False

    content_overlap = _table_content_overlap(left, right)
    if content_overlap <= 0.0:
        return False

    left_bbox = left.evidence.bbox
    right_bbox = right.evidence.bbox
    if left_bbox is not None and right_bbox is not None:
        return _bbox_similar(left_bbox, right_bbox) and content_overlap >= 0.5

    return content_overlap >= TABLE_CONTENT_OVERLAP_THRESHOLD


def _image_blocks_match(left: ImageBlock, right: ImageBlock) -> bool:
    if left.evidence.page != right.evidence.page:
        return False

    left_bbox = left.evidence.bbox
    right_bbox = right.evidence.bbox
    if left_bbox is not None and right_bbox is not None and _bbox_similar(left_bbox, right_bbox):
        return _image_metadata_compatible(left, right)

    if left.xref is not None and right.xref is not None:
        return left.xref == right.xref

    return _same_optional_value(left.width, right.width) and _same_optional_value(left.height, right.height)


def _choose_better_text_block(left: TextBlock, right: TextBlock) -> TextBlock:
    return left if _text_block_score(left) >= _text_block_score(right) else right


def _choose_better_table_block(left: TableBlock, right: TableBlock) -> TableBlock:
    return left if _table_block_score(left) >= _table_block_score(right) else right


def _merge_image_metadata(left: ImageBlock, right: ImageBlock) -> ImageBlock:
    preferred = left if _image_block_score(left) >= _image_block_score(right) else right
    other = right if preferred is left else left

    merged = preferred.model_copy(deep=True)
    for field_name in ("width", "height", "xref", "colorspace", "bits_per_component", "extension"):
        if getattr(merged, field_name) is None:
            setattr(merged, field_name, getattr(other, field_name))

    if merged.evidence.bbox is None and other.evidence.bbox is not None:
        merged.evidence.bbox = other.evidence.bbox

    if merged.evidence.confidence is None:
        merged.evidence.confidence = other.evidence.confidence

    return merged


def _text_block_score(block: TextBlock) -> tuple[float, int, int, int, int, int]:
    return (
        _confidence_score(block.evidence.confidence),
        _bbox_presence_score(block.evidence.bbox),
        _parser_priority(block.evidence.parser),
        -_text_noise_score(block.text),
        len(block.text.strip()),
        1 if block.kind != "paragraph" else 0,
    )


def _table_block_score(table: TableBlock) -> tuple[float, int, int, int, int]:
    return (
        _confidence_score(table.confidence if table.confidence is not None else table.evidence.confidence),
        _cell_bbox_count(table),
        _non_empty_cell_count(table),
        _bbox_presence_score(table.evidence.bbox),
        _parser_priority(table.evidence.parser),
    )


def _image_block_score(block: ImageBlock) -> tuple[float, int, int, int, int]:
    metadata_count = sum(
        value is not None
        for value in (
            block.width,
            block.height,
            block.xref,
            block.colorspace,
            block.bits_per_component,
            block.extension,
        )
    )
    return (
        _confidence_score(block.evidence.confidence),
        _bbox_presence_score(block.evidence.bbox),
        metadata_count,
        1 if block.xref is not None else 0,
        _parser_priority(block.evidence.parser),
    )


def _table_content_overlap(left: TableBlock, right: TableBlock) -> float:
    left_signature = _table_signature(left)
    right_signature = _table_signature(right)
    if not left_signature or not right_signature:
        return 0.0

    shared = len(left_signature & right_signature)
    total = max(len(left_signature), len(right_signature))
    return shared / total if total else 0.0


def _table_signature(table: TableBlock) -> set[tuple[int, int, str]]:
    signature: set[tuple[int, int, str]] = set()
    for cell in table.cells:
        normalized = _normalize_text(cell.text)
        if not normalized:
            continue
        signature.add((cell.row, cell.col, normalized))
    return signature


def _warning_key(warning: str) -> str:
    return re.sub(r"\s+", " ", warning).strip()


def _normalize_text(value: str) -> str:
    lowered = value.casefold()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _text_noise_score(value: str) -> int:
    leading_or_trailing = 0 if value == value.strip() else 1
    repeated_whitespace = len(re.findall(r"\s{2,}", value))
    return leading_or_trailing + repeated_whitespace


def _bbox_similar(left: BBox, right: BBox) -> bool:
    if _bbox_iou(left, right) >= IOU_THRESHOLD:
        return True

    return all(
        abs(left_value - right_value) <= COORDINATE_TOLERANCE
        for left_value, right_value in (
            (left.x0, right.x0),
            (left.y0, right.y0),
            (left.x1, right.x1),
            (left.y1, right.y1),
        )
    )


def _bbox_iou(left: BBox, right: BBox) -> float:
    inter_x0 = max(left.x0, right.x0)
    inter_y0 = max(left.y0, right.y0)
    inter_x1 = min(left.x1, right.x1)
    inter_y1 = min(left.y1, right.y1)

    inter_width = max(0.0, inter_x1 - inter_x0)
    inter_height = max(0.0, inter_y1 - inter_y0)
    intersection = inter_width * inter_height
    if intersection <= 0.0:
        return 0.0

    left_area = _bbox_area(left)
    right_area = _bbox_area(right)
    union = left_area + right_area - intersection
    if union <= 0.0:
        return 0.0

    return intersection / union


def _bbox_area(bbox: BBox) -> float:
    return max(0.0, bbox.x1 - bbox.x0) * max(0.0, bbox.y1 - bbox.y0)


def _image_metadata_compatible(left: ImageBlock, right: ImageBlock) -> bool:
    comparable_pairs = (
        (left.xref, right.xref),
        (left.width, right.width),
        (left.height, right.height),
    )
    for left_value, right_value in comparable_pairs:
        if left_value is not None and right_value is not None and left_value != right_value:
            return False
    return True


def _same_optional_value(left: int | None, right: int | None) -> bool:
    if left is None or right is None:
        return False
    return left == right


def _confidence_score(value: float | None) -> float:
    return float(value) if value is not None and not math.isnan(value) else -1.0


def _bbox_presence_score(bbox: BBox | None) -> int:
    return 1 if bbox is not None else 0


def _parser_priority(parser: str) -> int:
    return PARSER_PRIORITY.get(parser, 0)


def _cell_bbox_count(table: TableBlock) -> int:
    return sum(
        1
        for cell in table.cells
        if isinstance(cell, TableCell) and cell.evidence is not None and cell.evidence.bbox is not None
    )


def _non_empty_cell_count(table: TableBlock) -> int:
    return sum(1 for cell in table.cells if _normalize_text(cell.text))
