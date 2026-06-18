First build order

Do it in this order:

Implement PyMuPDF text + image detection fully.                         -> DONE
Implement Camelot table extraction.                                     -> DONE
Implement pdfplumber table fallback and debug image export.             -> DONE
Implement Docling parser and compare against deterministic output.      -> DONE
Implement Surya OCR for image regions only.                             -> DONE
    (test surya via: uv run dotenv run -- surya_ocr path/to/file)
Implement PaddleOCR fallback.                                           -> SKIP
Enhance pipeline: Use ocr only on regions that have been flagged; not on the whole document if not necessary. -> DONE
Enhance merge_documents: deduplicate by page + bbox + text similarity.
Implement local LLM schema extraction with strict JSON validation.
Build a gold-set evaluator before tuning prompts.

The key discipline: every extracted JSON field should carry evidence: page number, parser, method, and bounding box when available. That is what will separate a reliable offline system from a flashy demo.
