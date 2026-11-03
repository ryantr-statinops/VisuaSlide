from pathlib import Path

import pytest
from pydantic import ValidationError

from visuaslide.config import SourceConfig, load_config
from visuaslide.exceptions import ConfigurationError


def test_source_config_normalizes_ids_and_column_ranges() -> None:
    config = SourceConfig(
        spreadsheet_id="  synthetic-source-id  ",
        sheet_id=23,
        column_range="a:c",
    )

    assert config.spreadsheet_id == "synthetic-source-id"
    assert config.column_range == "A:C"


@pytest.mark.parametrize(
    "values",
    [
        {"spreadsheet_id": "sheet", "sheet_id": -1, "column_range": "A:C"},
        {"spreadsheet_id": "sheet", "sheet_id": True, "column_range": "A:C"},
        {"spreadsheet_id": "sheet", "sheet_id": 1, "column_range": "C:A"},
        {"spreadsheet_id": "sheet", "sheet_id": 1, "column_range": "A:C!A1"},
        {"spreadsheet_id": " ", "sheet_id": 1, "column_range": "A:C"},
    ],
)
def test_source_config_rejects_ambiguous_or_invalid_source(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SourceConfig.model_validate(values)


def test_load_config_resolves_relative_runtime_directory(tmp_path: Path) -> None:
    config_file = tmp_path / "survey.toml"
    config_file.write_text(
        'project_dir="runs"\n[source]\nspreadsheet_id="synthetic"\n'
        'sheet_id=0\ncolumn_range="A:D"\n'
        '[schema]\nvariables=[{name="result", source_header="Result", kind="text"}]\n',
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.project_dir == tmp_path / "runs"


def test_load_config_wraps_toml_parse_errors(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.toml"
    config_file.write_text("[source\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Invalid project configuration"):
        load_config(config_file)
