from pathlib import Path

from pdf_json_parser.models.document import ParsedDocument
from pdf_json_parser.models.extraction import ExtractionResult
from pdf_json_parser.parsers.docling_parser import DoclingParser
from pdf_json_parser.parsers.pymupdf_parser import PyMuPDFParser
from pdf_json_parser.parsers.pdfplumber_parser import PdfPlumberParser
from pdf_json_parser.parsers.camelot_parser import CamelotParser
from pdf_json_parser.parsers.surya_parser import SuryaParser
from pdf_json_parser.parsers.paddleocr_parser import PaddleOCRParser
from pdf_json_parser.stages.merge_candidates import merge_documents
from pdf_json_parser.stages.extract_schema import extract_schema_json
from pdf_json_parser.stages.validate_json import validate_extracted_json
from pdf_json_parser.stages.score_result import score_result


class PdfJsonPipeline:
    def __init__(self, debug_image_dir: Path | None = None) -> None:
        self.docling = DoclingParser()
        self.digital_parsers = [
            PyMuPDFParser(),
            PdfPlumberParser(debug_output_dir=debug_image_dir),
            CamelotParser(),
        ]
        self.ocr_parsers = [
            PaddleOCRParser(),
            SuryaParser(),
        ]

    def run(self, pdf_path: Path, schema_path: Path) -> ExtractionResult:
        docling_candidate: ParsedDocument | None = None
        deterministic_candidates: list[ParsedDocument] = []

        # Structured extraction is evaluated against deterministic parsers instead of
        # being merged into them blindly.
        try:
            docling_candidate = self.docling.parse(pdf_path)
        except Exception as e:
            print(f"[warning] Docling parser failed: {e}")
        
        # Deterministic digital PDF extraction remains the primary baseline.
        for parser in self.digital_parsers:
            try:
                deterministic_candidates.append(parser.parse(pdf_path))
            except Exception as e:
                print(f"[warning] Digital parser {parser.name} failed: {e}")
        
        if deterministic_candidates:
            merged = merge_documents(deterministic_candidates)
        elif docling_candidate is not None:
            merged = docling_candidate
            merged.warnings.append(
                "Using Docling output because deterministic parsers did not produce a candidate."
            )
        else:
            merged = ParsedDocument(source_path=str(pdf_path), page_count=0)

        if docling_candidate is not None:
            if merged is not docling_candidate:
                merged.warnings.extend(
                    f"{docling_candidate.source_path}: {warning}"
                    for warning in docling_candidate.warnings
                )
            if deterministic_candidates:
                merged.warnings.extend(
                    self._compare_docling_to_deterministic(docling_candidate, merged)
                )

        if self._needs_ocr(merged):
            candidates = [merged]
            for parser in self.ocr_parsers:
                try:
                    candidates.append(parser.parse(pdf_path))
                except Exception as e:
                    print(f"[warning] OCR parser {parser.name} failed: {e}")
            
            merged = merge_documents(candidates)

        merged.warnings = self._normalize_warnings(pdf_path, merged.warnings)
        
        extracted = extract_schema_json(merged, schema_path)
        schema_errors = validate_extracted_json(extracted, schema_path)

        result = ExtractionResult(
            document=merged,
            extracted_json=extracted,
            schema_errors=schema_errors,
            warnings=merged.warnings if hasattr(merged, 'warnings') else [],
        )
        result.score = score_result(result)

        return result

    def _compare_docling_to_deterministic(
        self,
        docling_document: ParsedDocument,
        deterministic_document: ParsedDocument,
    ) -> list[str]:
        docling_lines = self._normalized_text_lines(docling_document)
        deterministic_lines = self._normalized_text_lines(deterministic_document)
        shared_lines = docling_lines & deterministic_lines
        denominator = len(deterministic_lines) or 1
        overlap = len(shared_lines) / denominator

        warnings = [
            "Docling comparison against deterministic output: "
            f"text_blocks={len(docling_document.text_blocks)}/{len(deterministic_document.text_blocks)}, "
            f"tables={len(docling_document.tables)}/{len(deterministic_document.tables)}, "
            f"line_overlap={overlap:.3f}"
        ]

        if deterministic_lines and overlap < 0.5:
            warnings.append(
                "Docling text diverges from deterministic output "
                f"(normalized line overlap {overlap:.3f})."
            )

        if len(docling_document.tables) != len(deterministic_document.tables):
            warnings.append(
                "Docling table count differs from deterministic output "
                f"({len(docling_document.tables)} vs {len(deterministic_document.tables)})."
            )

        return warnings

    def _normalized_text_lines(self, document: ParsedDocument) -> set[str]:
        normalized_lines: set[str] = set()
        for block in document.text_blocks:
            normalized = " ".join(block.text.split()).strip().lower()
            if normalized:
                normalized_lines.add(normalized)
        return normalized_lines

    def _normalize_warnings(self, pdf_path: Path, warnings: list[str]) -> list[str]:
        source_prefix = f"{pdf_path}: "
        normalized: list[str] = []
        seen: set[str] = set()

        for warning in warnings:
            cleaned = warning.strip()
            while cleaned.startswith(source_prefix):
                cleaned = cleaned[len(source_prefix):].strip()

            if cleaned.startswith("Docling "):
                cleaned = f"{source_prefix}{cleaned}"
            elif warning.startswith(source_prefix):
                cleaned = f"{source_prefix}{cleaned}"

            if cleaned in seen:
                continue

            seen.add(cleaned)
            normalized.append(cleaned)

        return normalized

    def _needs_ocr(self, document: ParsedDocument) -> bool:
        # Implement logic to determine if OCR is needed based on the merged document.   
        total_chars = sum(len(block.text.strip()) for block in document.text_blocks)
        has_tables = len(document.tables) > 0

        if total_chars < 50:
            print("[info] Low text content detected. OCR may be needed.")
            return True

        if not has_tables:
            print("[info] No tables detected. OCR may be needed.")
            return True

        if document.image_blocks:
            print("[info] Embedded images detected. OCR may be needed.")
            return True

        if any("embedded image" in warning.lower() for warning in document.warnings):
            print("[info] Embedded images detected. OCR may be needed.")
            return True

        return False
    
