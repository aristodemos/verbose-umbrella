from pdf_json_parser.models.extraction import ExtractionResult


def score_result(result: ExtractionResult) -> float:
    score = 1.0

    if result.schema_errors:
        score -= min(0.5, len(result.schema_errors) * 0.05)
    
    if not result.document.text_blocks:
        score -= 0.3
    
    if not result.document.tables:
        score -= 0.1
    
    return max(0.0, round(score, 3))
