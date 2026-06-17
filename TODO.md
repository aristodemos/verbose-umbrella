First build order

Do it in this order:

Implement PyMuPDF text + image detection fully.
Implement Camelot table extraction.
Implement pdfplumber table fallback and debug image export.
Implement Docling parser and compare against deterministic output.
Implement Surya OCR for image regions only.
Implement PaddleOCR fallback.
Implement local LLM schema extraction with strict JSON validation.
Build a gold-set evaluator before tuning prompts.

The key discipline: every extracted JSON field should carry evidence: page number, parser, method, and bounding box when available. That is what will separate a reliable offline system from a flashy demo.