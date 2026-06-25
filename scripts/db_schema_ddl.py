import sqlite3
from pathlib import Path


def create_pdf_knowledge_db(db_path: str | Path) -> None:
    """
    Create a SQLite schema for:
    - parsed PDF structure
    - raw pipeline JSON
    - blocks, tables, cells, OCR/image regions
    - semantic entities, mentions, records, facts, relations
    - extraction runs and provenance

    Requires SQLite with JSON1 extension enabled, which is included in most
    modern Python SQLite builds.
    """

    db_path = Path(db_path)

    ddl = """
    PRAGMA foreign_keys = ON;
    PRAGMA journal_mode = WAL;

    -------------------------------------------------------------------------
    -- Documents and parse runs
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        filename TEXT NOT NULL,
        source_uri TEXT,
        doc_hash TEXT UNIQUE,

        document_type TEXT,
        title TEXT,

        metadata_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS document_parse_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        parser_name TEXT,
        parser_version TEXT,

        raw_json TEXT NOT NULL,

        status TEXT NOT NULL DEFAULT 'completed',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
    );

    -------------------------------------------------------------------------
    -- Physical / layout structure
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        parse_run_id INTEGER,

        page_number INTEGER NOT NULL,
        width REAL,
        height REAL,
        rotation INTEGER DEFAULT 0,

        image_uri TEXT,
        metadata_json TEXT,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (parse_run_id) REFERENCES document_parse_runs(id) ON DELETE SET NULL,

        UNIQUE (document_id, page_number)
    );

    CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        page_id INTEGER NOT NULL,
        parse_run_id INTEGER,

        parent_block_id INTEGER,

        block_type TEXT NOT NULL,
        -- examples:
        -- paragraph, heading, list_item, header, footer, caption,
        -- image_ocr, table_text, form_field, annotation

        text TEXT,
        normalized_text TEXT,

        bbox_json TEXT,
        -- recommended shape:
        -- {"x0": 10.2, "y0": 15.8, "x1": 300.0, "y1": 80.0}

        reading_order INTEGER,
        confidence REAL,

        metadata_json TEXT,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE,
        FOREIGN KEY (parse_run_id) REFERENCES document_parse_runs(id) ON DELETE SET NULL,
        FOREIGN KEY (parent_block_id) REFERENCES blocks(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        page_id INTEGER NOT NULL,
        parse_run_id INTEGER,

        bbox_json TEXT,

        row_count INTEGER,
        column_count INTEGER,
        confidence REAL,

        caption TEXT,
        metadata_json TEXT,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE,
        FOREIGN KEY (parse_run_id) REFERENCES document_parse_runs(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS table_cells (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        table_id INTEGER NOT NULL,
        document_id INTEGER NOT NULL,
        page_id INTEGER NOT NULL,

        row_index INTEGER NOT NULL,
        column_index INTEGER NOT NULL,

        row_span INTEGER DEFAULT 1,
        column_span INTEGER DEFAULT 1,

        text TEXT,
        normalized_text TEXT,

        bbox_json TEXT,
        confidence REAL,

        is_header INTEGER DEFAULT 0,
        metadata_json TEXT,

        FOREIGN KEY (table_id) REFERENCES tables(id) ON DELETE CASCADE,
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE CASCADE,

        UNIQUE (table_id, row_index, column_index)
    );

    -------------------------------------------------------------------------
    -- Extraction runs
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS extraction_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,

        run_type TEXT NOT NULL,
        -- examples:
        -- entity_extraction, fact_extraction, relation_extraction,
        -- table_interpretation, normalization

        model_name TEXT,
        prompt_version TEXT,
        schema_version TEXT,

        status TEXT NOT NULL DEFAULT 'completed',
        error_message TEXT,

        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        metadata_json TEXT,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
    );

    -------------------------------------------------------------------------
    -- Semantic entities and mentions
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        entity_type TEXT NOT NULL,
        -- examples:
        -- person, company, organization, location, product,
        -- contract, clause, obligation, asset, regulation, metric

        canonical_name TEXT NOT NULL,
        normalized_key TEXT,

        attributes_json TEXT,

        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        UNIQUE (entity_type, normalized_key)
    );

    CREATE TABLE IF NOT EXISTS entity_mentions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        entity_id INTEGER,

        document_id INTEGER NOT NULL,
        extraction_run_id INTEGER,

        mention_text TEXT NOT NULL,
        normalized_mention_text TEXT,

        source_block_id INTEGER,
        source_cell_id INTEGER,

        page_id INTEGER,
        bbox_json TEXT,

        confidence REAL,
        metadata_json TEXT,

        FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL,
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (extraction_run_id) REFERENCES extraction_runs(id) ON DELETE SET NULL,
        FOREIGN KEY (source_block_id) REFERENCES blocks(id) ON DELETE SET NULL,
        FOREIGN KEY (source_cell_id) REFERENCES table_cells(id) ON DELETE SET NULL,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE SET NULL
    );

    -------------------------------------------------------------------------
    -- Records: typed semantic objects extracted from a document
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        extraction_run_id INTEGER,

        record_type TEXT NOT NULL,
        -- examples:
        -- contract_clause, invoice_header, invoice_line_item,
        -- inspection_finding, property_attribute, financial_metric

        record_key TEXT,
        -- optional stable key within the document, e.g. line item number,
        -- clause number, section title, etc.

        title TEXT,
        attributes_json TEXT,

        source_block_id INTEGER,
        source_cell_id INTEGER,
        page_id INTEGER,
        bbox_json TEXT,

        confidence REAL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (extraction_run_id) REFERENCES extraction_runs(id) ON DELETE SET NULL,
        FOREIGN KEY (source_block_id) REFERENCES blocks(id) ON DELETE SET NULL,
        FOREIGN KEY (source_cell_id) REFERENCES table_cells(id) ON DELETE SET NULL,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE SET NULL
    );

    -------------------------------------------------------------------------
    -- Facts: EAV / RDF-like semantic facts
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        extraction_run_id INTEGER,

        record_id INTEGER,

        subject_entity_id INTEGER,
        subject_label TEXT,

        predicate TEXT NOT NULL,

        object_entity_id INTEGER,

        object_text TEXT,
        object_number REAL,
        object_date TEXT,
        object_boolean INTEGER,
        object_json TEXT,

        unit TEXT,

        qualifiers_json TEXT,
        -- examples:
        -- {"currency": "EUR", "period": "monthly", "condition": "upon written notice"}

        evidence_text TEXT,

        source_block_id INTEGER,
        source_cell_id INTEGER,
        page_id INTEGER,
        bbox_json TEXT,

        confidence REAL,

        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (extraction_run_id) REFERENCES extraction_runs(id) ON DELETE SET NULL,
        FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE SET NULL,

        FOREIGN KEY (subject_entity_id) REFERENCES entities(id) ON DELETE SET NULL,
        FOREIGN KEY (object_entity_id) REFERENCES entities(id) ON DELETE SET NULL,

        FOREIGN KEY (source_block_id) REFERENCES blocks(id) ON DELETE SET NULL,
        FOREIGN KEY (source_cell_id) REFERENCES table_cells(id) ON DELETE SET NULL,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE SET NULL
    );

    -------------------------------------------------------------------------
    -- Relations: entity-to-entity links
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        document_id INTEGER NOT NULL,
        extraction_run_id INTEGER,

        subject_entity_id INTEGER NOT NULL,
        relation_type TEXT NOT NULL,
        object_entity_id INTEGER NOT NULL,

        qualifiers_json TEXT,
        evidence_text TEXT,

        source_block_id INTEGER,
        source_cell_id INTEGER,
        page_id INTEGER,
        bbox_json TEXT,

        confidence REAL,

        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
        FOREIGN KEY (extraction_run_id) REFERENCES extraction_runs(id) ON DELETE SET NULL,

        FOREIGN KEY (subject_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
        FOREIGN KEY (object_entity_id) REFERENCES entities(id) ON DELETE CASCADE,

        FOREIGN KEY (source_block_id) REFERENCES blocks(id) ON DELETE SET NULL,
        FOREIGN KEY (source_cell_id) REFERENCES table_cells(id) ON DELETE SET NULL,
        FOREIGN KEY (page_id) REFERENCES pages(id) ON DELETE SET NULL
    );

    -------------------------------------------------------------------------
    -- Optional semantic index metadata
    --
    -- SQLite is not ideal for vector search, but this table lets you track
    -- embeddings generated for blocks, records, facts, etc.
    -- You can store vectors as JSON or BLOB in dev, then later move to
    -- PostgreSQL + pgvector, LanceDB, Qdrant, etc.
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS embeddings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        owner_type TEXT NOT NULL,
        -- document, page, block, table_cell, record, fact, entity

        owner_id INTEGER NOT NULL,

        embedding_model TEXT NOT NULL,
        embedding_json TEXT,
        embedding_blob BLOB,

        text_for_embedding TEXT,

        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

        UNIQUE (owner_type, owner_id, embedding_model)
    );

    -------------------------------------------------------------------------
    -- Controlled vocabulary / ontology-lite
    -------------------------------------------------------------------------

    CREATE TABLE IF NOT EXISTS predicate_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        predicate TEXT NOT NULL UNIQUE,

        description TEXT,
        expected_value_type TEXT,
        -- text, number, date, boolean, entity, json

        allowed_units_json TEXT,
        examples_json TEXT,

        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS entity_type_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        entity_type TEXT NOT NULL UNIQUE,
        description TEXT,
        examples_json TEXT,

        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS record_type_definitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        record_type TEXT NOT NULL UNIQUE,
        description TEXT,
        schema_json TEXT,
        examples_json TEXT,

        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    -------------------------------------------------------------------------
    -- Indexes
    -------------------------------------------------------------------------

    CREATE INDEX IF NOT EXISTS idx_documents_doc_hash
        ON documents (doc_hash);

    CREATE INDEX IF NOT EXISTS idx_pages_document_page
        ON pages (document_id, page_number);

    CREATE INDEX IF NOT EXISTS idx_blocks_document
        ON blocks (document_id);

    CREATE INDEX IF NOT EXISTS idx_blocks_page
        ON blocks (page_id);

    CREATE INDEX IF NOT EXISTS idx_blocks_type
        ON blocks (block_type);

    CREATE INDEX IF NOT EXISTS idx_blocks_reading_order
        ON blocks (document_id, page_id, reading_order);

    CREATE INDEX IF NOT EXISTS idx_tables_document
        ON tables (document_id);

    CREATE INDEX IF NOT EXISTS idx_table_cells_table_pos
        ON table_cells (table_id, row_index, column_index);

    CREATE INDEX IF NOT EXISTS idx_table_cells_document
        ON table_cells (document_id);

    CREATE INDEX IF NOT EXISTS idx_extraction_runs_document
        ON extraction_runs (document_id, run_type, created_at);

    CREATE INDEX IF NOT EXISTS idx_entities_type_name
        ON entities (entity_type, canonical_name);

    CREATE INDEX IF NOT EXISTS idx_entities_normalized_key
        ON entities (normalized_key);

    CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity
        ON entity_mentions (entity_id);

    CREATE INDEX IF NOT EXISTS idx_entity_mentions_document
        ON entity_mentions (document_id);

    CREATE INDEX IF NOT EXISTS idx_records_document_type
        ON records (document_id, record_type);

    CREATE INDEX IF NOT EXISTS idx_facts_document
        ON facts (document_id);

    CREATE INDEX IF NOT EXISTS idx_facts_predicate
        ON facts (predicate);

    CREATE INDEX IF NOT EXISTS idx_facts_subject_entity
        ON facts (subject_entity_id);

    CREATE INDEX IF NOT EXISTS idx_facts_object_entity
        ON facts (object_entity_id);

    CREATE INDEX IF NOT EXISTS idx_facts_number
        ON facts (predicate, object_number);

    CREATE INDEX IF NOT EXISTS idx_facts_date
        ON facts (predicate, object_date);

    CREATE INDEX IF NOT EXISTS idx_relations_subject
        ON relations (subject_entity_id);

    CREATE INDEX IF NOT EXISTS idx_relations_object
        ON relations (object_entity_id);

    CREATE INDEX IF NOT EXISTS idx_relations_type
        ON relations (relation_type);

    CREATE INDEX IF NOT EXISTS idx_embeddings_owner
        ON embeddings (owner_type, owner_id);

    -------------------------------------------------------------------------
    -- Full-text search
    -------------------------------------------------------------------------

    CREATE VIRTUAL TABLE IF NOT EXISTS blocks_fts
    USING fts5(
        text,
        normalized_text,
        content='blocks',
        content_rowid='id'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS table_cells_fts
    USING fts5(
        text,
        normalized_text,
        content='table_cells',
        content_rowid='id'
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
    USING fts5(
        subject_label,
        predicate,
        object_text,
        evidence_text,
        content='facts',
        content_rowid='id'
    );

    -------------------------------------------------------------------------
    -- FTS triggers
    -------------------------------------------------------------------------

    CREATE TRIGGER IF NOT EXISTS blocks_ai
    AFTER INSERT ON blocks
    BEGIN
        INSERT INTO blocks_fts(rowid, text, normalized_text)
        VALUES (new.id, new.text, new.normalized_text);
    END;

    CREATE TRIGGER IF NOT EXISTS blocks_ad
    AFTER DELETE ON blocks
    BEGIN
        INSERT INTO blocks_fts(blocks_fts, rowid, text, normalized_text)
        VALUES ('delete', old.id, old.text, old.normalized_text);
    END;

    CREATE TRIGGER IF NOT EXISTS blocks_au
    AFTER UPDATE ON blocks
    BEGIN
        INSERT INTO blocks_fts(blocks_fts, rowid, text, normalized_text)
        VALUES ('delete', old.id, old.text, old.normalized_text);

        INSERT INTO blocks_fts(rowid, text, normalized_text)
        VALUES (new.id, new.text, new.normalized_text);
    END;

    CREATE TRIGGER IF NOT EXISTS table_cells_ai
    AFTER INSERT ON table_cells
    BEGIN
        INSERT INTO table_cells_fts(rowid, text, normalized_text)
        VALUES (new.id, new.text, new.normalized_text);
    END;

    CREATE TRIGGER IF NOT EXISTS table_cells_ad
    AFTER DELETE ON table_cells
    BEGIN
        INSERT INTO table_cells_fts(table_cells_fts, rowid, text, normalized_text)
        VALUES ('delete', old.id, old.text, old.normalized_text);
    END;

    CREATE TRIGGER IF NOT EXISTS table_cells_au
    AFTER UPDATE ON table_cells
    BEGIN
        INSERT INTO table_cells_fts(table_cells_fts, rowid, text, normalized_text)
        VALUES ('delete', old.id, old.text, old.normalized_text);

        INSERT INTO table_cells_fts(rowid, text, normalized_text)
        VALUES (new.id, new.text, new.normalized_text);
    END;

    CREATE TRIGGER IF NOT EXISTS facts_ai
    AFTER INSERT ON facts
    BEGIN
        INSERT INTO facts_fts(rowid, subject_label, predicate, object_text, evidence_text)
        VALUES (new.id, new.subject_label, new.predicate, new.object_text, new.evidence_text);
    END;

    CREATE TRIGGER IF NOT EXISTS facts_ad
    AFTER DELETE ON facts
    BEGIN
        INSERT INTO facts_fts(facts_fts, rowid, subject_label, predicate, object_text, evidence_text)
        VALUES ('delete', old.id, old.subject_label, old.predicate, old.object_text, old.evidence_text);
    END;

    CREATE TRIGGER IF NOT EXISTS facts_au
    AFTER UPDATE ON facts
    BEGIN
        INSERT INTO facts_fts(facts_fts, rowid, subject_label, predicate, object_text, evidence_text)
        VALUES ('delete', old.id, old.subject_label, old.predicate, old.object_text, old.evidence_text);

        INSERT INTO facts_fts(rowid, subject_label, predicate, object_text, evidence_text)
        VALUES (new.id, new.subject_label, new.predicate, new.object_text, new.evidence_text);
    END;
    """

    with sqlite3.connect(db_path) as conn:
        conn.executescript(ddl)
        conn.commit()


if __name__ == "__main__":
    create_pdf_knowledge_db("pdf_knowledge_dev.sqlite")
    print("Created SQLite database: pdf_knowledge_dev.sqlite")