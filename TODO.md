First build order

Do it in this order:

Implement PyMuPDF text + image detection fully.                         -> DONE
Implement Camelot table extraction.                                     -> DONE
Implement pdfplumber table fallback and debug image export.             -> DONE
Implement Docling parser and compare against deterministic output.      -> DONE
Implement Surya OCR for image regions only.                             -> DONE
Implement PaddleOCR fallback.
Enhance merge_documents: deduplicate by page + bbox + text similarity.
Implement local LLM schema extraction with strict JSON validation.
Build a gold-set evaluator before tuning prompts.

The key discipline: every extracted JSON field should carry evidence: page number, parser, method, and bounding box when available. That is what will separate a reliable offline system from a flashy demo.