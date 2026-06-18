# Greek PDF JSON Parser

Offline pipeline for extracting structured JSON from generated Greek PDFs containing paragraphs, tables, and occasional embedded images.

## Pipeline

1. Docling structured PDF parsing
2. Native PDF extraction with PyMuPDF, pdfplumber, and Camelot
3. OCR/VLM fallback with Surya, PaddleOCR, and local vision models
4. Candidate merging
5. Local LLM schema extraction
6. JSON Schema validation
7. Evidence and confidence scoring

## Setup

```bash
uv sync --extra dev --extra docling --extra ocr --extra llm
```

### TO run
```bash
uv run pdf-json-parser data/input/somatosensory.pdf
  --schema configs/schemas/default_document.schema.json \
  --output data/output/example.result.json
```

## Offline model policy
All model weights must be stored under models/.
No runtime downloads are allowed in production.

