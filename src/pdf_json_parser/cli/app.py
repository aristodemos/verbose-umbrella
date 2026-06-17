from pathlib import Path

import orjson
import typer
from rich.console import Console

from pdf_json_parser.core.pipeline import PdfJsonPipeline

app = typer.Typer()
console = Console()


@app.command()
def parse(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to the PDF file to be parsed."),
    schema: Path = typer.Option(
        Path("configs/schemas/default_document.schema.json"),
        "--schema",
        "-s"
    ),
    output: Path = typer.Option(
        Path("data/output/result.json"),
        "--output",
        "-o",
        help="Path to the output JSON file."
    ),
) -> None:
    """
    Parse a PDF file and extract structured JSON data based on the provided schema.
    """
    console.print(f"[bold green]Parsing PDF:[/bold green] {pdf}")
    console.print(f"[bold blue]Using schema:[/bold blue] {schema}")
    console.print(f"[bold yellow]Output will be saved to:[/bold yellow] {output}")

    pipeline = PdfJsonPipeline()
    result = pipeline.run(pdf, schema)

    # Ensure the output directory exists
    output.parent.mkdir(parents=True, exist_ok=True)

    # Save the extracted JSON to the specified output file
    output.write_bytes(
        orjson.dumps(
            result.model_dump(mode="json"), 
            option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS,
        )
    )

    console.print(f"[bold green]Extraction completed successfully![/bold green]")
    console.print(f"Score: {result.score}")
    console.print(f"Schema Errors: {len(result.schema_errors)}")


if __name__ == "__main__":
    app()
    