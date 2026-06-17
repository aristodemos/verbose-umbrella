from pdf_json_parser.models.document import ParsedDocument


def merge_documents(candidates: list[ParsedDocument]) -> ParsedDocument:
    """
    Merge multiple ParsedDocument instances into a single ParsedDocument.
    This function combines the content, warnings, and other relevant information
    from the input documents.

    Args:
        candidates (list[ParsedDocument]): List of ParsedDocument instances to merge.
    """
    if not candidates:
        raise ValueError("No candidates provided for merging.")
    
    # Start with the candidate with the most text blocks as the base for merging.
    best = max(
        candidates, 
        key=lambda doc: (len(doc.tables), 
                         sum(len(block.text) for block in doc.text_blocks),
        ),
    )

    merged = ParsedDocument(
        source_path=best.source_path,
        language=best.language,
        page_count=max(doc.page_count for doc in candidates)
    )

    # Naive first pass. Later: deduplicate by page + bbox + text similarity.
    for doc in candidates:
        merged.text_blocks.extend(doc.text_blocks)
        merged.tables.extend(doc.tables)
        merged.warnings.extend(f"{doc.source_path}: {warning}" for warning in doc.warnings)
    
    return merged