"""Project configuration models and loading."""

from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from visuaslide.exceptions import ConfigurationError


class StrictModel(BaseModel):
    """Base model that rejects unrecognized configuration keys."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


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


class VariableKind(StrEnum):
    """Supported types for a survey response column."""

    CATEGORICAL = "categorical"
    NUMERIC = "numeric"
    DATETIME = "datetime"
    TEXT = "text"


class VariableSchema(StrictModel):
    """Declared meaning and preparation policy for one input column."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source_header: str = Field(min_length=1)
    kind: VariableKind
    required: bool = False
    missing_values: tuple[str, ...] = ("",)
    categories: tuple[str, ...] = ()
    datetime_format: str | None = None
    timezone: str | None = None
    trim_whitespace: bool = False

    @field_validator("source_header")
    @classmethod
    def strip_source_header(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_header cannot be blank")
        return cleaned

    @field_validator("categories", "missing_values")
    @classmethod
    def reject_duplicate_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("configured values must be unique")
        return values

    @model_validator(mode="after")
    def check_kind_options(self) -> VariableSchema:
        if self.kind == VariableKind.CATEGORICAL and not self.categories:
            raise ValueError("categorical variables require an explicit category list")
        if self.kind != VariableKind.CATEGORICAL and self.categories:
            raise ValueError("categories are only valid for categorical variables")
        if self.kind == VariableKind.DATETIME and not self.datetime_format:
            raise ValueError("datetime variables require an explicit datetime_format")
        if self.kind != VariableKind.DATETIME and (self.datetime_format or self.timezone):
            raise ValueError("datetime_format and timezone are only valid for datetime variables")
        return self


class SurveySchema(StrictModel):
    """Column schema for the single configured survey tab."""

    variables: tuple[VariableSchema, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_columns(self) -> SurveySchema:
        names = [variable.name for variable in self.variables]
        headers = [variable.source_header for variable in self.variables]
        if len(names) != len(set(names)):
            raise ValueError("variable names must be unique")
        if len(headers) != len(set(headers)):
            raise ValueError("source headers must be unique")
        return self


class PercentageDenominator(StrEnum):
    """Response population used to calculate a single-variable percentage."""

    NON_MISSING = "non_missing"
    ALL_RESPONSES = "all_responses"


class PercentageBasis(StrEnum):
    """Normalization basis for a crosstab percentage."""

    ROW = "row"
    COLUMN = "column"
    ALL = "all"


class FrequencyAnalysis(StrictModel):
    """A frequency table for a configured variable."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["frequency"]
    variable: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    denominator: PercentageDenominator


class NumericSummaryAnalysis(StrictModel):
    """Descriptive statistics for one numeric variable."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["numeric_summary"]
    variable: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


class CrosstabAnalysis(StrictModel):
    """A two-variable frequency table with an explicit normalization basis."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["crosstab"]
    row_variable: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    column_variable: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    percentage_basis: PercentageBasis

    @model_validator(mode="after")
    def require_distinct_variables(self) -> CrosstabAnalysis:
        if self.row_variable == self.column_variable:
            raise ValueError("crosstab variables must be different")
        return self


AnalysisSpecification = Annotated[
    FrequencyAnalysis | NumericSummaryAnalysis | CrosstabAnalysis,
    Field(discriminator="kind"),
]


class AnalysisConfig(StrictModel):
    """Ordered analysis requests configured for the survey."""

    specifications: tuple[AnalysisSpecification, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_ids(self) -> AnalysisConfig:
        ids = [specification.id for specification in self.specifications]
        if len(ids) != len(set(ids)):
            raise ValueError("analysis IDs must be unique")
        return self


class ProjectConfig(StrictModel):
    """Minimum project configuration required to identify a source."""

    source: SourceConfig
    survey_schema: SurveySchema = Field(alias="schema")
    analysis: AnalysisConfig
    project_dir: Path = Path(".visuaslide")

    @model_validator(mode="after")
    def validate_analysis_references(self) -> ProjectConfig:
        variables = {variable.name: variable for variable in self.survey_schema.variables}
        for specification in self.analysis.specifications:
            if isinstance(specification, FrequencyAnalysis):
                variable = variables.get(specification.variable)
                if variable is None or variable.kind != VariableKind.CATEGORICAL:
                    raise ValueError(
                        f"frequency analysis {specification.id!r} requires a categorical variable"
                    )
            elif isinstance(specification, NumericSummaryAnalysis):
                variable = variables.get(specification.variable)
                if variable is None or variable.kind != VariableKind.NUMERIC:
                    raise ValueError(
                        f"numeric summary {specification.id!r} requires a numeric variable"
                    )
            else:
                row_variable = variables.get(specification.row_variable)
                column_variable = variables.get(specification.column_variable)
                if (
                    row_variable is None
                    or column_variable is None
                    or row_variable.kind != VariableKind.CATEGORICAL
                    or column_variable.kind != VariableKind.CATEGORICAL
                ):
                    raise ValueError(
                        f"crosstab {specification.id!r} requires two categorical variables"
                    )
        return self


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
