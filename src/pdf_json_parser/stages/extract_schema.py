from pathlib import Path
from typing import Any

from pdf_json_parser.models.document import ParsedDocument



def extract_schema_json(document: ParsedDocument) -> dict[str, Any]:
    """
    Extracts a JSON representation of the schema from a ParsedDocument.

    Args:
        document (ParsedDocument): The parsed document from which to extract the schema.

    Returns:
        dict[str, Any]: A dictionary representing the extracted schema.
    """
    # TODO:
    # 1. Build markdown/context from ParsedDocument.
    # 2. Use LLM with strict JSON grammar or function-style schema to extract schema from the markdown/context.
    # 3. Normalize text - if needed (e.g. dates, currency, etc)
    return {
        "language": document.language,
        "source_path": document.source_path,
        "page_count": document.page_count,
        "text_block_count": len(document.text_blocks),
        "table_count": len(document.table),
    }
