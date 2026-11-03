"""Typed, serializable results returned by public SDK operations."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from visuaslide.config import StrictModel

type Scalar = str | int | float | bool | None


class ValidationIssue(StrictModel):
    """Safe description of an invalid source cell without its raw value."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    variable: str | None = None
    source_row: int | None = Field(default=None, ge=1)


class ValidationReport(StrictModel):
    """Outcome and row counts from validating one stored snapshot."""

    snapshot_id: str = Field(min_length=1)
    input_rows: int = Field(ge=0)
    blank_rows: int = Field(ge=0)
    accepted_rows: int = Field(ge=0)
    invalid_rows: int = Field(ge=0)
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def check_row_counts(self) -> ValidationReport:
        if self.input_rows != self.blank_rows + self.accepted_rows + self.invalid_rows:
            raise ValueError("input_rows must equal blank_rows + accepted_rows + invalid_rows")
        if (self.invalid_rows == 0) != (len(self.issues) == 0):
            raise ValueError("issues must be present exactly when rows are invalid")
        return self

    @property
    def is_valid(self) -> bool:
        return self.invalid_rows == 0


class AnalysisTable(StrictModel):
    """A tabular result with named columns and immutable scalar rows."""

    analysis_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    columns: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[Scalar, ...], ...]

    @model_validator(mode="after")
    def check_row_widths(self) -> AnalysisTable:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("each analysis row must have the same width as columns")
        return self


class Statistic(StrictModel):
    """One scalar statistic with optional percentage provenance."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: Scalar
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    unit: str | None = None

    @model_validator(mode="after")
    def check_percentage_provenance(self) -> Statistic:
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("numerator and denominator must be supplied together")
        if self.numerator is not None and self.denominator is not None:
            if self.numerator > self.denominator:
                raise ValueError("numerator cannot exceed denominator")
            if self.denominator == 0 and self.value is not None:
                raise ValueError("a statistic with a zero denominator must be undefined")
        return self


class AnalysisResult(StrictModel):
    """Analysis results and source counts for one immutable run."""

    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    created_at: datetime
    input_rows: int = Field(ge=0)
    accepted_rows: int = Field(ge=0)
    statistics: tuple[Statistic, ...] = ()
    tables: tuple[AnalysisTable, ...] = ()

    @field_validator("created_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def check_unique_result_ids(self) -> AnalysisResult:
        statistic_names = [statistic.name for statistic in self.statistics]
        table_ids = [table.analysis_id for table in self.tables]
        if len(statistic_names) != len(set(statistic_names)):
            raise ValueError("statistic names must be unique")
        if len(table_ids) != len(set(table_ids)):
            raise ValueError("analysis table IDs must be unique")
        if self.accepted_rows > self.input_rows:
            raise ValueError("accepted_rows cannot exceed input_rows")
        return self


class RunStatus(StrEnum):
    """Lifecycle states for an acquisition or publication run."""

    RUNNING = "running"
    VALIDATION_FAILED = "validation_failed"
    READY = "ready"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"


class RunResult(StrictModel):
    """Safe current state and output references for one pipeline run."""

    run_id: str = Field(min_length=1)
    status: RunStatus
    stage: str = Field(min_length=1)
    updated_at: datetime
    snapshot_id: str | None = None
    error_code: str | None = None
    analysis: AnalysisResult | None = None
    output_urls: dict[str, str] = Field(default_factory=dict)

    @field_validator("updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def check_completed_result(self) -> RunResult:
        if self.status == RunStatus.COMPLETED and self.analysis is None:
            raise ValueError("completed runs require an analysis result")
        if self.analysis is not None and self.analysis.run_id != self.run_id:
            raise ValueError("analysis result must belong to the run")
        return self
