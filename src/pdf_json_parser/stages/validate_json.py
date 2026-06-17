from pathlib import Path
from typing import Any

import json
from jsonschema import Draft202012Validator


def validate_extracted_json(data: dict[str, Any], schema_path: Path) -> list[str]:
    """
    Validates the extracted JSON against a given JSON schema.

    Args:
        data (dict[str, Any]): The JSON data to validate.
        schema_path (Path): The path to the JSON schema file.

    Returns:
        list[str]: A list of validation error messages. Empty if valid.
    """
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found at {schema_path}")

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    return [f"{error.message} at {'/'.join(map(str, error.path))}" for error in validator.iter_errors(data)]
