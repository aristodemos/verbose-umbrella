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
    def __init__(self) -> None:
        self.docling = DoclingParser()
        self.digital_parsers = [
            PyMuPDFParser(),
            PdfPlumberParser(),
            CamelotParser(),
        ]
        self.ocr_parsers = [
            PaddleOCRParser(),
            SuryaParser(),
        ]

    def run(self, pdf_path: Path, schema_path: Path) -> ExtractionResult:
        candidates: list[ParsedDocument] = []

        # Option 1: Docling-first structured extraction.
        try:
            candidates.append(self.docling.parse(pdf_path))
        except Exception as e:
            print(f"[warning] Docling parser failed: {e}")
        
        # Option 2: Deterministic Digital PDF extraction.
        for parser in self.digital_parsers:
            try:
                candidates.append(parser.parse(pdf_path))
            except Exception as e:
                print(f"[warning] Digital parser {parser.name} failed: {e}")
        
        # Merge current result and decide whether OCR is needed.
        merged = merge_documents(candidates)

        if self._needs_ocr(merged):
            for parser in self.ocr_parsers:
                try:
                    candidates.append(parser.parse(pdf_path))
                except Exception as e:
                    print(f"[warning] OCR parser {parser.name} failed: {e}")
            
            merged = merge_documents(candidates)
        
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

    def _needs_ocr(self, document: ParsedDocument) -> bool:
        # Implement logic to determine if OCR is needed based on the merged document.   
        total_chars = sum(len(block.text.strip()) for block in document.text_blocks)
        has_tables = len(document.table) > 0

        if total_chars < 50:
            print("[info] Low text content detected. OCR may be needed.")
            return True

        if not has_tables:
            print("[info] No tables detected. OCR may be needed.")
            return True

        if any("embedded image" in warning.lower() for warning in document.warnings):
            print("[info] Embedded images detected. OCR may be needed.")
            return True

        return False
    