"""Project configuration models and loading."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from visuaslide.exceptions import ConfigurationError


class StrictModel(BaseModel):
    """Base model that rejects unrecognized configuration keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceConfig(StrictModel):
    """Identity and rectangular read range of one Google Sheets tab."""

    spreadsheet_id: str = Field(min_length=1)
    sheet_id: int = Field(ge=0, strict=True)
    header_row: int = Field(default=1, ge=1, strict=True)
    column_range: str = Field(pattern=r"^[A-Za-z]+:[A-Za-z]+$")

    @field_validator("spreadsheet_id")
    @classmethod
    def strip_spreadsheet_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("spreadsheet_id cannot be blank")
        return cleaned

    @field_validator("column_range")
    @classmethod
    def normalize_column_range(cls, value: str) -> str:
        start, end = value.upper().split(":", maxsplit=1)
        if _column_number(start) > _column_number(end):
            raise ValueError("column_range start must not be after its end")
        return f"{start}:{end}"


class ProjectConfig(StrictModel):
    """Minimum project configuration required to identify a source."""

    source: SourceConfig
    project_dir: Path = Path(".visuaslide")


def load_config(path: str | Path) -> ProjectConfig:
    """Read and validate a TOML project configuration."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as file:
            raw: dict[str, Any] = tomllib.load(file)
        if "project_dir" in raw:
            project_dir = Path(raw["project_dir"])
            raw["project_dir"] = (
                project_dir if project_dir.is_absolute() else config_path.parent / project_dir
            )
        return ProjectConfig.model_validate(raw)
    except (OSError, tomllib.TOMLDecodeError, ValidationError, TypeError) as exc:
        raise ConfigurationError(f"Invalid project configuration at {config_path}: {exc}") from exc


def _column_number(column: str) -> int:
    number = 0
    for char in column:
        number = number * 26 + ord(char) - ord("A") + 1
    return number
