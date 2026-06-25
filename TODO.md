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


### LLM extraction plan
The cleanest roadmap is to treat the LLM as a `proposal engine`, not the source of truth.

Right now the pipeline already has the right seam for this in [extract_schema.py](/home/metis/lab/verbose-umbrella/src/pdf_json_parser/stages/extract_schema.py:1), after deterministic parsing/merging in [pipeline.py](/home/metis/lab/verbose-umbrella/src/pdf_json_parser/core/pipeline.py:1). What’s missing is a strict intermediate contract between “document understanding” and “final relational data.” I’d avoid having the LLM emit the final business schema directly on day one.

**Recommended architecture**

1. Build a layout-aware document context layer.
   Use the merged `ParsedDocument` to create ordered semantic chunks: title, section heading, paragraph, caption, table, image region, nearby text. Because placement matters, this should preserve page, bbox, reading order, and parent/neighbor relationships rather than flattening everything into plain markdown.

2. Define an intermediate `SemanticFact` schema.
   The LLM should emit facts like:
   `entity`, `attribute`, `relation`, `classification`, `table_row_fact`, `document_metadata`.
   Each fact should carry `fact_type`, `subject`, `predicate`, `object/value`, `evidence_refs`, `confidence`, and maybe `status=proposed`.
   This gives us something strict to validate while still letting the model express meaning.

3. Add a local LLM adapter with constrained JSON output.
   Make this provider-agnostic so we can back it with local `transformers`, `vLLM`, `ollama`, or `llama.cpp`. The output contract should be enforced twice:
   first by structured generation if the backend supports it, then by Pydantic/JSON Schema validation in code.

4. Add a deterministic post-LLM stage: verify, normalize, merge, reject.
   This is the core safety layer.
   `verify`: evidence exists, page/bbox refs are valid, fact shape is valid, referenced text/table cells actually exist.
   `normalize`: canonical entity names, enums, units, dates, whitespace, dehyphenation, relation direction.
   `merge`: dedupe semantically equivalent facts, combine evidence, resolve aliases.
   `reject`: unsupported entity types, missing evidence, contradictions, low-confidence orphan facts, hallucinated fields not grounded in the document.

5. Only then map accepted facts into the target relational model.
   That mapping should be deterministic and testable. If a fact can’t be mapped cleanly, keep it in a review bucket rather than forcing it into the final schema.

**Why this fits your use case**

The “subtitle before content” problem is really a layout semantics problem, not just a prompt problem. So I’d explicitly model document structure first:
`block graph -> semantic facts -> normalized domain records`

That will also help with tables and images:
- a heading can scope the paragraphs that follow
- a caption can scope a nearby image/table
- a table row can become multiple candidate facts
- OCR/image-derived text can still participate if it has evidence and location

**Concrete implementation order**

1. Lock the target relational model and define the intermediate fact schema.
2. Implement a `context builder` from `ParsedDocument` with layout relationships.
3. Implement local LLM adapter plus strict response parsing.
4. Implement `verify/normalize/merge/reject` as a new stage after extraction.
5. Update the final JSON schema so it validates actual business output, not just counts.
6. Build a small gold set before prompt tuning.

**A few things I’d fix or account for while doing this**

- The current JSON schema in [default_document.schema.json](/home/metis/lab/verbose-umbrella/configs/schemas/default_document.schema.json:1) is still placeholder-level, so we’ll need a richer schema for semantic output.
- Docling table titles are currently leaking object repr strings in the sample output, so we should sanitize parser artifacts before sending context to the LLM.
- The merge layer today is geometric/textual; we’ll want a second merge layer for semantic facts.

My recommendation for our next action is: define the intermediate `SemanticFact` contract and the final relational target side by side before writing any model code. That will keep the LLM integration narrow, testable, and hard to hallucinate against.

If you want, I can turn this roadmap into a concrete implementation plan for the repo with proposed modules, model classes, and test cases next.