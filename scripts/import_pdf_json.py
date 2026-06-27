import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    text = text.strip()

    return text or None


def clean_inline_text(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None

    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip() or None


def normalize_key(value: Any) -> str:
    text = clean_inline_text(value) or ""
    text = text.lower()

    # Repair a few common OCR/header artifacts from the sample.
    text = text.replace("notam i number", "notam number")
    text = text.replace("ssuing authority", "issuing authority")

    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")

    aliases = {
        "notam_number": "notam_number",
        "NOTAM":"notam_number",
        "navtex_number": "navtex_number",
        "issuing_authority": "issuing_authority",
        "polygon_coordinates": "polygon_coordinates",
        "ΣΥΝΤΕΤΑΓΜΕΝΕΣ": "polygon_coordinates",
        "effective_altitudes": "effective_altitudes",
        "date_start": "date_start",
        "ΗΜΕΡ":"date_start",
        "ΥΨΟΣ":"effective_altitudes",
        "date_end": "date_end",
        "times_of_day_effective_start_end": "times_of_day_effective",
        "brief_on_liner_description": "brief_description",
        "ΕΙ∆ΟΣ": "brief_description",
        "date_time_issued": "date_time_issued",
        "coverage_area": "coverage_area",
        "content_summary": "content_summary",
        "operational_relevance": "operational_relevance",
        "callsign": "callsign",
        "nationality": "nationality",
        "brief_purpose_or_mission": "mission",
        "date_of_arrival": "date_of_arrival",
        "expected_date_of_departure": "expected_date_of_departure",
        "airplane_model_type": "airplane_model_type",
    }

    return aliases.get(text, text or "unknown")


def normalize_date(value: str | None) -> str | None:
    """
    Handles sample values like:
    - 2024-\n05-01
    - 2024-05-01
    - Present
    """
    if not value:
        return None

    text = clean_inline_text(value)
    if not text:
        return None

    compact = text.replace(" ", "")

    if compact.lower() in {"present", "ongoing", "current"}:
        return None

    match = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", compact)
    if not match:
        return None

    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def normalize_number(value: str | None) -> float | None:
    if not value:
        return None

    text = clean_inline_text(value)
    if not text:
        return None

    match = re.search(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?", text)
    if not match:
        return None

    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def make_hash(path: Path, raw: bytes) -> str:
    h = hashlib.sha256()
    h.update(str(path.name).encode("utf-8"))
    h.update(b"\n")
    h.update(raw)
    return h.hexdigest()


def bbox_from_evidence(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    if not evidence:
        return None
    return evidence.get("bbox")


def page_number_from_evidence(evidence: dict[str, Any] | None) -> int | None:
    if not evidence:
        return None
    page = evidence.get("page")
    return int(page) if page is not None else None


def infer_record_type(headers: list[str]) -> str:
    header_set = set(headers)

    if "notam_number" in header_set:
        return "notam"
    if "navtex_number" in header_set:
        return "navtex"
    if "callsign" in header_set and "airplane_model_type" in header_set:
        return "aircraft_mission"
    if "issuing_authority" in header_set:
        return "issued_notice"

    return "table_row"


def ensure_page(
    conn: sqlite3.Connection,
    document_id: int,
    parse_run_id: int,
    page_number: int,
) -> int:
    conn.execute(
        """
        INSERT OR IGNORE INTO pages (
            document_id,
            parse_run_id,
            page_number
        )
        VALUES (?, ?, ?)
        """,
        (document_id, parse_run_id, page_number),
    )

    row = conn.execute(
        """
        SELECT id
        FROM pages
        WHERE document_id = ?
          AND page_number = ?
        """,
        (document_id, page_number),
    ).fetchone()

    return int(row["id"])


def insert_entity(
    conn: sqlite3.Connection,
    entity_type: str,
    canonical_name: str,
    attributes: dict[str, Any] | None = None,
) -> int:
    normalized_key = normalize_key(canonical_name)

    conn.execute(
        """
        INSERT OR IGNORE INTO entities (
            entity_type,
            canonical_name,
            normalized_key,
            attributes_json
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            entity_type,
            canonical_name,
            normalized_key,
            json_dumps(attributes or {}),
        ),
    )

    row = conn.execute(
        """
        SELECT id
        FROM entities
        WHERE entity_type = ?
          AND normalized_key = ?
        """,
        (entity_type, normalized_key),
    ).fetchone()

    return int(row["id"])


def insert_entity_mention(
    conn: sqlite3.Connection,
    *,
    entity_id: int,
    document_id: int,
    extraction_run_id: int | None,
    mention_text: str,
    source_cell_id: int | None = None,
    source_block_id: int | None = None,
    page_id: int | None = None,
    bbox: dict[str, Any] | None = None,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO entity_mentions (
            entity_id,
            document_id,
            extraction_run_id,
            mention_text,
            normalized_mention_text,
            source_block_id,
            source_cell_id,
            page_id,
            bbox_json,
            confidence,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            document_id,
            extraction_run_id,
            mention_text,
            normalize_key(mention_text),
            source_block_id,
            source_cell_id,
            page_id,
            json_dumps(bbox),
            confidence,
            json_dumps(metadata or {}),
        ),
    )

    return int(cur.lastrowid)


def insert_document_and_parse_run(
    conn: sqlite3.Connection,
    json_path: Path,
    payload: dict[str, Any],
    raw_bytes: bytes,
) -> tuple[int, int]:
    document = payload.get("document", {})
    source_path = document.get("source_path") or str(json_path)
    filename = Path(source_path).name or json_path.name
    doc_hash = make_hash(json_path, raw_bytes)

    metadata = {
        "language": document.get("language"),
        "page_count": document.get("page_count"),
        "score": payload.get("score"),
        "warnings": payload.get("warnings") or document.get("warnings") or [],
        "schema_errors": payload.get("schema_errors") or [],
        "extracted_json": payload.get("extracted_json"),
    }

    conn.execute(
        """
        INSERT OR IGNORE INTO documents (
            filename,
            source_uri,
            doc_hash,
            document_type,
            title,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            filename,
            source_path,
            doc_hash,
            None,
            None,
            json_dumps(metadata),
        ),
    )

    document_row = conn.execute(
        """
        SELECT id
        FROM documents
        WHERE doc_hash = ?
        """,
        (doc_hash,),
    ).fetchone()

    document_id = int(document_row["id"])

    cur = conn.execute(
        """
        INSERT INTO document_parse_runs (
            document_id,
            parser_name,
            parser_version,
            raw_json,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            document_id,
            "custom_pdf_pipeline",
            None,
            json_dumps(payload),
            "completed",
        ),
    )

    parse_run_id = int(cur.lastrowid)
    return document_id, parse_run_id


def insert_pages(
    conn: sqlite3.Connection,
    document_id: int,
    parse_run_id: int,
    document: dict[str, Any],
) -> dict[int, int]:
    page_count = int(document.get("page_count") or 0)
    page_id_by_number: dict[int, int] = {}

    for page_number in range(1, page_count + 1):
        page_id_by_number[page_number] = ensure_page(
            conn,
            document_id,
            parse_run_id,
            page_number,
        )

    return page_id_by_number


def insert_text_blocks(
    conn: sqlite3.Connection,
    document_id: int,
    parse_run_id: int,
    document: dict[str, Any],
    page_id_by_number: dict[int, int],
) -> list[int]:
    block_ids: list[int] = []

    text_blocks = document.get("text_blocks") or []

    for index, block in enumerate(text_blocks):
        evidence = block.get("evidence") or {}
        page_number = page_number_from_evidence(evidence) or 1
        page_id = page_id_by_number.get(page_number)
        if page_id is None:
            page_id = ensure_page(conn, document_id, parse_run_id, page_number)
            page_id_by_number[page_number] = page_id

        text = clean_text(block.get("text"))
        kind = block.get("kind") or "paragraph"
        bbox = bbox_from_evidence(evidence)

        metadata = {
            "raw": block,
            "evidence": evidence,
        }

        cur = conn.execute(
            """
            INSERT INTO blocks (
                document_id,
                page_id,
                parse_run_id,
                parent_block_id,
                block_type,
                text,
                normalized_text,
                bbox_json,
                reading_order,
                confidence,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                page_id,
                parse_run_id,
                None,
                kind,
                text,
                clean_inline_text(text),
                json_dumps(bbox),
                index,
                evidence.get("confidence"),
                json_dumps(metadata),
            ),
        )

        block_ids.append(int(cur.lastrowid))

    return block_ids


def insert_image_blocks(
    conn: sqlite3.Connection,
    document_id: int,
    parse_run_id: int,
    document: dict[str, Any],
    page_id_by_number: dict[int, int],
    start_reading_order: int = 100000,
) -> list[int]:
    block_ids: list[int] = []

    image_blocks = document.get("image_blocks") or []

    for index, block in enumerate(image_blocks):
        evidence = block.get("evidence") or {}
        page_number = page_number_from_evidence(evidence) or block.get("page") or 1
        page_number = int(page_number)

        page_id = page_id_by_number.get(page_number)
        if page_id is None:
            page_id = ensure_page(conn, document_id, parse_run_id, page_number)
            page_id_by_number[page_number] = page_id

        text = clean_text(
            block.get("text")
            or block.get("ocr_text")
            or block.get("caption")
            or ""
        )

        bbox = bbox_from_evidence(evidence) or block.get("bbox")

        metadata = {
            "raw": block,
            "evidence": evidence,
        }

        cur = conn.execute(
            """
            INSERT INTO blocks (
                document_id,
                page_id,
                parse_run_id,
                parent_block_id,
                block_type,
                text,
                normalized_text,
                bbox_json,
                reading_order,
                confidence,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                page_id,
                parse_run_id,
                None,
                "image_ocr",
                text,
                clean_inline_text(text),
                json_dumps(bbox),
                start_reading_order + index,
                evidence.get("confidence") or block.get("confidence"),
                json_dumps(metadata),
            ),
        )

        block_ids.append(int(cur.lastrowid))

    return block_ids


def insert_tables_and_cells(
    conn: sqlite3.Connection,
    document_id: int,
    parse_run_id: int,
    document: dict[str, Any],
    page_id_by_number: dict[int, int],
) -> tuple[dict[tuple[int, int, int], int], list[int]]:
    """
    Returns:
    - cell_id_by_table_row_col: {(table_id, row, col): cell_id}
    - table_ids
    """
    cell_id_by_table_row_col: dict[tuple[int, int, int], int] = {}
    table_ids: list[int] = []

    for table_index, table in enumerate(document.get("tables") or []):
        evidence = table.get("evidence") or {}
        page_number = int(table.get("page") or page_number_from_evidence(evidence) or 1)

        page_id = page_id_by_number.get(page_number)
        if page_id is None:
            page_id = ensure_page(conn, document_id, parse_run_id, page_number)
            page_id_by_number[page_number] = page_id

        cells = table.get("cells") or []
        max_row = max((int(c.get("row", 0)) for c in cells), default=-1)
        max_col = max((int(c.get("col", 0)) for c in cells), default=-1)

        cur = conn.execute(
            """
            INSERT INTO tables (
                document_id,
                page_id,
                parse_run_id,
                bbox_json,
                row_count,
                column_count,
                confidence,
                caption,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                page_id,
                parse_run_id,
                json_dumps(bbox_from_evidence(evidence)),
                max_row + 1,
                max_col + 1,
                table.get("confidence") or evidence.get("confidence"),
                clean_inline_text(table.get("title")),
                json_dumps(
                    {
                        "raw_table_index": table_index,
                        "evidence": evidence,
                    }
                ),
            ),
        )

        table_id = int(cur.lastrowid)
        table_ids.append(table_id)

        for cell in cells:
            cell_evidence = cell.get("evidence") or {}
            row_index = int(cell.get("row", 0))
            column_index = int(cell.get("col", 0))
            cell_text = clean_text(cell.get("text"))

            cur = conn.execute(
                """
                INSERT INTO table_cells (
                    table_id,
                    document_id,
                    page_id,
                    row_index,
                    column_index,
                    row_span,
                    column_span,
                    text,
                    normalized_text,
                    bbox_json,
                    confidence,
                    is_header,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    table_id,
                    document_id,
                    page_id,
                    row_index,
                    column_index,
                    int(cell.get("rowspan") or 1),
                    int(cell.get("colspan") or 1),
                    cell_text,
                    clean_inline_text(cell_text),
                    json_dumps(bbox_from_evidence(cell_evidence)),
                    cell_evidence.get("confidence"),
                    1 if row_index == 0 else 0,
                    json_dumps(
                        {
                            "raw": cell,
                            "evidence": cell_evidence,
                        }
                    ),
                ),
            )

            cell_id_by_table_row_col[(table_id, row_index, column_index)] = int(cur.lastrowid)

    return cell_id_by_table_row_col, table_ids


def create_extraction_run(conn: sqlite3.Connection, document_id: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO extraction_runs (
            document_id,
            run_type,
            model_name,
            prompt_version,
            schema_version,
            status,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            "table_row_fact_extraction",
            "deterministic_parser",
            "v1",
            "dev_sqlite_v1",
            "completed",
            json_dumps(
                {
                    "description": "Creates one record per table row and one fact per non-empty cell using table headers."
                }
            ),
        ),
    )

    return int(cur.lastrowid)


def insert_semantic_records_and_facts_from_tables(
    conn: sqlite3.Connection,
    document_id: int,
    extraction_run_id: int,
) -> None:
    table_rows = conn.execute(
        """
        SELECT id, page_id, caption
        FROM tables
        WHERE document_id = ?
        ORDER BY id
        """,
        (document_id,),
    ).fetchall()

    for table_row in table_rows:
        table_id = int(table_row["id"])
        page_id = int(table_row["page_id"])

        cells = conn.execute(
            """
            SELECT id, row_index, column_index, text, bbox_json, confidence
            FROM table_cells
            WHERE table_id = ?
            ORDER BY row_index, column_index
            """,
            (table_id,),
        ).fetchall()

        if not cells:
            continue

        cells_by_row: dict[int, list[sqlite3.Row]] = {}
        for cell in cells:
            cells_by_row.setdefault(int(cell["row_index"]), []).append(cell)

        header_cells = cells_by_row.get(0, [])
        header_by_col = {
            int(cell["column_index"]): normalize_key(cell["text"])
            for cell in header_cells
        }

        if not header_by_col:
            continue

        headers = [header_by_col[col] for col in sorted(header_by_col)]
        record_type = infer_record_type(headers)

        for row_index, row_cells in sorted(cells_by_row.items()):
            if row_index == 0:
                continue

            attrs: dict[str, Any] = {}
            source_cell_id = None
            record_key = None
            record_title = None

            for cell in row_cells:
                col = int(cell["column_index"])
                key = header_by_col.get(col, f"column_{col}")
                value = clean_inline_text(cell["text"])

                if not value:
                    continue

                attrs[key] = value

                if source_cell_id is None:
                    source_cell_id = int(cell["id"])

                if key in {
                    "notam_number",
                    "navtex_number",
                    "callsign",
                }:
                    record_key = value
                    record_title = value

            if not attrs:
                continue

            cur = conn.execute(
                """
                INSERT INTO records (
                    document_id,
                    extraction_run_id,
                    record_type,
                    record_key,
                    title,
                    attributes_json,
                    source_cell_id,
                    page_id,
                    bbox_json,
                    confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    extraction_run_id,
                    record_type,
                    record_key,
                    record_title,
                    json_dumps(attrs),
                    source_cell_id,
                    page_id,
                    None,
                    None,
                ),
            )

            record_id = int(cur.lastrowid)

            # Optional entity extraction from table row fields.
            entity_id_by_key: dict[str, int] = {}

            for entity_key, entity_type in {
                "issuing_authority": "organization",
                "nationality": "country",
                "callsign": "aircraft",
                "airplane_model_type": "aircraft_model",
            }.items():
                value = attrs.get(entity_key)
                if not value:
                    continue

                entity_id = insert_entity(
                    conn,
                    entity_type=entity_type,
                    canonical_name=value,
                    attributes={"source": "table_row"},
                )
                entity_id_by_key[entity_key] = entity_id

            # Insert facts, one per non-empty cell.
            for cell in row_cells:
                col = int(cell["column_index"])
                predicate = header_by_col.get(col, f"column_{col}")
                text_value = clean_inline_text(cell["text"])

                if not text_value:
                    continue

                source_cell_id_for_fact = int(cell["id"])
                bbox = json.loads(cell["bbox_json"]) if cell["bbox_json"] else None

                object_number = None
                object_date = None
                object_entity_id = None
                object_text = text_value
                unit = None

                if predicate in {
                    "date_start",
                    "date_end",
                    "date_of_arrival",
                    "expected_date_of_departure",
                }:
                    object_date = normalize_date(text_value)

                elif predicate in {
                    "effective_altitudes",
                }:
                    object_number = normalize_number(text_value)
                    if "ft" in text_value.lower():
                        unit = "ft"

                if predicate in entity_id_by_key:
                    object_entity_id = entity_id_by_key[predicate]

                conn.execute(
                    """
                    INSERT INTO facts (
                        document_id,
                        extraction_run_id,
                        record_id,
                        subject_entity_id,
                        subject_label,
                        predicate,
                        object_entity_id,
                        object_text,
                        object_number,
                        object_date,
                        object_boolean,
                        object_json,
                        unit,
                        qualifiers_json,
                        evidence_text,
                        source_cell_id,
                        page_id,
                        bbox_json,
                        confidence
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        extraction_run_id,
                        record_id,
                        None,
                        record_title or record_key or f"{record_type}:{record_id}",
                        predicate,
                        object_entity_id,
                        object_text,
                        object_number,
                        object_date,
                        None,
                        None,
                        unit,
                        json_dumps({"record_type": record_type, "table_id": table_id, "row_index": row_index}),
                        text_value,
                        source_cell_id_for_fact,
                        page_id,
                        json_dumps(bbox),
                        cell["confidence"],
                    ),
                )

                # Entity mention points to exact cell.
                if predicate in entity_id_by_key:
                    insert_entity_mention(
                        conn,
                        entity_id=entity_id_by_key[predicate],
                        document_id=document_id,
                        extraction_run_id=extraction_run_id,
                        mention_text=text_value,
                        source_cell_id=source_cell_id_for_fact,
                        page_id=page_id,
                        bbox=bbox,
                        confidence=cell["confidence"],
                        metadata={"predicate": predicate, "record_id": record_id},
                    )


def import_pdf_json(sqlite_path: Path, json_path: Path) -> int:
    raw_bytes = json_path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))

    document = payload.get("document")
    if not isinstance(document, dict):
        raise ValueError("Expected top-level payload['document'] to be an object.")

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")

        document_id, parse_run_id = insert_document_and_parse_run(
            conn,
            json_path,
            payload,
            raw_bytes,
        )

        page_id_by_number = insert_pages(
            conn,
            document_id,
            parse_run_id,
            document,
        )

        insert_text_blocks(
            conn,
            document_id,
            parse_run_id,
            document,
            page_id_by_number,
        )

        insert_image_blocks(
            conn,
            document_id,
            parse_run_id,
            document,
            page_id_by_number,
        )

        insert_tables_and_cells(
            conn,
            document_id,
            parse_run_id,
            document,
            page_id_by_number,
        )

        extraction_run_id = create_extraction_run(conn, document_id)

        insert_semantic_records_and_facts_from_tables(
            conn,
            document_id,
            extraction_run_id,
        )

        conn.commit()

        return document_id


def print_import_summary(sqlite_path: Path, document_id: int) -> None:
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row

        tables = [
            "documents",
            "document_parse_runs",
            "pages",
            "blocks",
            "tables",
            "table_cells",
            "extraction_runs",
            "records",
            "facts",
            "entities",
            "entity_mentions",
        ]

        print(f"Imported document_id={document_id}")
        print()

        for table in tables:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE document_id = ?"
                if table not in {"documents", "entities"}
                else (
                    "SELECT COUNT(*) AS n FROM documents WHERE id = ?"
                    if table == "documents"
                    else "SELECT COUNT(*) AS n FROM entities"
                ),
                (document_id,) if table != "entities" else (),
            ).fetchone()

            print(f"{table:24s} {row['n']}")

        print()
        print("Sample extracted facts:")
        rows = conn.execute(
            """
            SELECT subject_label, predicate, object_text, object_number, object_date, unit
            FROM facts
            WHERE document_id = ?
            ORDER BY id
            LIMIT 12
            """,
            (document_id,),
        ).fetchall()

        for row in rows:
            print(
                f"- {row['subject_label']} | {row['predicate']} | "
                f"text={row['object_text']!r} number={row['object_number']} "
                f"date={row['object_date']} unit={row['unit']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import parsed PDF JSON into the SQLite PDF knowledge schema."
    )
    parser.add_argument(
        "json_path",
        type=Path,
        help="Path to the parsed PDF JSON file.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("pdf_knowledge_dev.sqlite"),
        help="Path to the SQLite database created with the schema DDL.",
    )

    args = parser.parse_args()

    if not args.json_path.exists():
        raise FileNotFoundError(args.json_path)

    if not args.db.exists():
        raise FileNotFoundError(
            f"SQLite database does not exist: {args.db}. "
            "Create it first using the DDL script."
        )

    document_id = import_pdf_json(args.db, args.json_path)
    print_import_summary(args.db, document_id)


if __name__ == "__main__":
    main()