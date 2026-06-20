from pdf_json_parser.models.document import ImageBlock, ParsedDocument, TableBlock, TableCell, TextBlock
from pdf_json_parser.models.geometry import BBox, Evidence
from pdf_json_parser.stages.merge_candidates import merge_documents


def _text_block(
    text: str,
    *,
    page: int = 1,
    parser: str,
    bbox: BBox | None,
    confidence: float | None = 1.0,
    kind: str = "paragraph",
) -> TextBlock:
    return TextBlock(
        text=text,
        kind=kind,
        evidence=Evidence(
            page=page,
            bbox=bbox,
            method="native_pdf_text" if parser != "surya" else "ocr_image_region",
            parser=parser,
            confidence=confidence,
        ),
    )


def _table_block(
    rows: list[list[str]],
    *,
    page: int = 1,
    parser: str,
    bbox: BBox | None,
    confidence: float | None,
) -> TableBlock:
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        for col_index, text in enumerate(row):
            cells.append(
                TableCell(
                    text=text,
                    row=row_index,
                    col=col_index,
                    evidence=Evidence(
                        page=page,
                        bbox=bbox,
                        method="lines",
                        parser=parser,
                        confidence=confidence,
                    ),
                )
            )

    return TableBlock(
        page=page,
        cells=cells,
        evidence=Evidence(
            page=page,
            bbox=bbox,
            method="lines",
            parser=parser,
            confidence=confidence,
        ),
        confidence=confidence,
    )


def _image_block(
    *,
    page: int = 1,
    parser: str,
    bbox: BBox | None,
    width: int | None = None,
    height: int | None = None,
    xref: int | None = None,
    confidence: float | None = 1.0,
    extension: str | None = None,
) -> ImageBlock:
    return ImageBlock(
        width=width,
        height=height,
        xref=xref,
        extension=extension,
        evidence=Evidence(
            page=page,
            bbox=bbox,
            method="embedded_image_object",
            parser=parser,
            confidence=confidence,
        ),
    )


def test_merge_documents_deduplicates_text_blocks_and_keeps_new_ocr_content() -> None:
    pdf_path = "sample.pdf"
    native_bbox = BBox(x0=10, y0=20, x1=120, y1=40)

    pymupdf_document = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        text_blocks=[
            _text_block("Invoice 123", parser="pymupdf", bbox=native_bbox),
        ],
        warnings=["Embedded image objects detected on page 1: 1"],
    )
    pdfplumber_document = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        text_blocks=[
            _text_block(" invoice   123 ", parser="pdfplumber", bbox=BBox(x0=11, y0=20, x1=119, y1=40)),
            _text_block("Total due", parser="pdfplumber", bbox=BBox(x0=10, y0=50, x1=90, y1=68)),
        ],
        warnings=["Embedded image objects detected on page 1: 1"],
    )
    surya_document = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        text_blocks=[
            _text_block("Invoice 123", parser="surya", bbox=BBox(x0=9, y0=19, x1=121, y1=41), confidence=0.82),
            _text_block("Scanned stamp", parser="surya", bbox=BBox(x0=180, y0=220, x1=260, y1=245), confidence=0.91),
        ],
        warnings=["  Embedded image objects detected on page 1: 1  "],
    )

    merged = merge_documents([pymupdf_document, pdfplumber_document, surya_document])

    assert len(merged.text_blocks) == 3
    assert [block.text for block in merged.text_blocks] == ["Invoice 123", "Total due", "Scanned stamp"]
    assert merged.text_blocks[0].evidence.parser == "pymupdf"
    assert merged.warnings == [f"{pdf_path}: Embedded image objects detected on page 1: 1"]


def test_merge_documents_deduplicates_tables_and_prefers_stronger_evidence() -> None:
    pdf_path = "sample.pdf"
    shared_rows = [["Item", "Amount"], ["Tax", "12.00"]]

    camelot_document = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        tables=[
            _table_block(
                shared_rows,
                parser="camelot",
                bbox=BBox(x0=30, y0=100, x1=220, y1=180),
                confidence=0.95,
            )
        ],
    )
    pdfplumber_document = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        tables=[
            _table_block(
                shared_rows,
                parser="pdfplumber",
                bbox=BBox(x0=31, y0=101, x1=221, y1=179),
                confidence=0.75,
            ),
            _table_block(
                [["Footer", "Value"]],
                parser="pdfplumber",
                bbox=BBox(x0=30, y0=210, x1=180, y1=235),
                confidence=0.75,
            ),
        ],
    )

    merged = merge_documents([camelot_document, pdfplumber_document])

    assert len(merged.tables) == 2
    assert merged.tables[0].evidence.parser == "camelot"
    assert merged.tables[0].confidence == 0.95
    assert [(cell.row, cell.col, cell.text) for cell in merged.tables[0].cells] == [
        (0, 0, "Item"),
        (0, 1, "Amount"),
        (1, 0, "Tax"),
        (1, 1, "12.00"),
    ]
    assert merged.tables[1].cells[0].text == "Footer"


def test_merge_documents_deduplicates_image_regions_and_keeps_richer_metadata() -> None:
    pdf_path = "sample.pdf"
    bbox = BBox(x0=72, y0=120, x1=172, y1=220)

    sparse_image = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        image_blocks=[
            _image_block(
                parser="surya",
                bbox=BBox(x0=73, y0=121, x1=171, y1=219),
                width=100,
                height=100,
                confidence=0.8,
            )
        ],
    )
    rich_image = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        image_blocks=[
            _image_block(
                parser="pymupdf",
                bbox=bbox,
                width=100,
                height=100,
                xref=42,
                extension="png",
                confidence=1.0,
            )
        ],
    )

    merged = merge_documents([sparse_image, rich_image])

    assert len(merged.image_blocks) == 1
    image = merged.image_blocks[0]
    assert image.evidence.parser == "pymupdf"
    assert image.width == 100
    assert image.height == 100
    assert image.xref == 42
    assert image.extension == "png"


def test_merge_documents_preserves_distinct_warnings() -> None:
    pdf_path = "sample.pdf"
    first = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        warnings=[
            "Embedded image objects detected on page 1: 1",
            "pdfplumber text-based table fallback used on page 1",
        ],
    )
    second = ParsedDocument(
        source_path=pdf_path,
        page_count=1,
        warnings=[
            " Embedded image objects detected on page 1: 1 ",
            "Embedded image objects detected on page 2: 1",
        ],
    )

    merged = merge_documents([first, second])

    assert merged.warnings == [
        f"{pdf_path}: Embedded image objects detected on page 1: 1",
        f"{pdf_path}: pdfplumber text-based table fallback used on page 1",
        f"{pdf_path}: Embedded image objects detected on page 2: 1",
    ]
