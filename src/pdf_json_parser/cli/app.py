from pathlib import Path

import orjson
import typer
import yaml
from rich.console import Console

from pdf_json_parser.core.pipeline import PdfJsonPipeline

app = typer.Typer()
console = Console()


def _load_enabled_parsers_from_config(config_path: Path | None) -> set[str] | None:
    if config_path is None or not config_path.exists():
        return None

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    parser_config = config.get("pipeline", {}).get("parsers", {})
    selected_parsers = parser_config.get("selected")
    if selected_parsers:
        return {str(parser).strip().lower() for parser in selected_parsers if str(parser).strip()}

    enabled: set[str] = set()

    if parser_config.get("docling", {}).get("enabled", False):
        enabled.add("docling")

    digital_config = parser_config.get("digital", {})
    if digital_config.get("enabled", False):
        for name, is_enabled in (digital_config.get("engines", {}) or {}).items():
            if is_enabled:
                enabled.add(str(name).strip().lower())

    ocr_config = parser_config.get("ocr", {})
    if ocr_config.get("enabled", False):
        for name, is_enabled in (ocr_config.get("engines", {}) or {}).items():
            if is_enabled:
                enabled.add(str(name).strip().lower())

    return enabled or None


def _resolve_enabled_parsers(
    parsers: list[str] | None,
    pipeline_config: Path | None,
) -> set[str] | None:
    if parsers:
        selected: set[str] = set()
        for parser_value in parsers:
            selected.update(
                part.strip().lower()
                for part in parser_value.split(",")
                if part.strip()
            )
        return selected or None

    return _load_enabled_parsers_from_config(pipeline_config)


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
    debug_images_dir: Path | None = typer.Option(
        None,
        "--debug-images-dir",
        help="Optional directory where pdfplumber page debug renders will be exported.",
    ),
    parsers: list[str] | None = typer.Option(
        None,
        "--parser",
        "-p",
        help="Parser name to run. Repeat the option or pass a comma-separated list.",
    ),
    pipeline_config: Path | None = typer.Option(
        Path("configs/pipeline.yaml"),
        "--pipeline-config",
        help="Optional pipeline config file used for default parser enablement.",
    ),
) -> None:
    """
    Parse a PDF file and extract structured JSON data based on the provided schema.
    """
    console.print(f"[bold green]Parsing PDF:[/bold green] {pdf}")
    console.print(f"[bold blue]Using schema:[/bold blue] {schema}")
    console.print(f"[bold yellow]Output will be saved to:[/bold yellow] {output}")
    if debug_images_dir is not None:
        console.print(f"[bold magenta]Debug images will be saved to:[/bold magenta] {debug_images_dir}")

    enabled_parsers = _resolve_enabled_parsers(parsers, pipeline_config)
    if enabled_parsers is not None:
        console.print(
            "[bold cyan]Enabled parsers:[/bold cyan] "
            + ", ".join(sorted(enabled_parsers))
        )

    try:
        pipeline = PdfJsonPipeline(
            debug_image_dir=debug_images_dir,
            enabled_parsers=enabled_parsers,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--parser") from exc

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
    
