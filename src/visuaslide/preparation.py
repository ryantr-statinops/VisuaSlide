"""Schema-driven preparation of survey columns."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from visuaslide.config import VariableKind, VariableSchema
from visuaslide.models import Scalar, ValidationIssue
from visuaslide.snapshots import SourceSnapshot


@dataclass(frozen=True)
class PreparedColumn:
    """Normalized values and safe validation issues for one declared column."""

    variable_name: str
    values: tuple[Scalar, ...]
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.issues


def prepare_categorical_column(
    snapshot: SourceSnapshot, variable: VariableSchema
) -> PreparedColumn:
    """Validate and normalize one categorical variable without inferring labels."""
    if variable.kind != VariableKind.CATEGORICAL:
        raise ValueError("prepare_categorical_column requires a categorical variable")

    try:
        column_index = snapshot.headers.index(variable.source_header)
    except ValueError:
        return PreparedColumn(
            variable_name=variable.name,
            values=(),
            issues=(
                ValidationIssue(
                    code="missing_configured_header",
                    message="A configured survey column is missing from the source.",
                    variable=variable.name,
                    source_row=snapshot.metadata.header_row,
                ),
            ),
        )

    values: list[Scalar] = []
    issues: list[ValidationIssue] = []
    allowed_categories = set(variable.categories)
    missing_values = set(variable.missing_values)

    for offset, row in enumerate(snapshot.rows):
        source_row = snapshot.source_first_row + offset
        if column_index >= len(row):
            value: object = None
        else:
            value = row[column_index]

        if value is None:
            normalized: Scalar = None
        elif not isinstance(value, str):
            issues.append(
                ValidationIssue(
                    code="invalid_categorical_type",
                    message="A categorical value must be text or an allowed missing value.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
            normalized = None
        else:
            normalized_text = value.strip() if variable.trim_whitespace else value
            if normalized_text in missing_values:
                normalized = None
            elif normalized_text not in allowed_categories:
                issues.append(
                    ValidationIssue(
                        code="unknown_category",
                        message="A categorical value is not in the configured category list.",
                        variable=variable.name,
                        source_row=source_row,
                    )
                )
                normalized = None
            else:
                normalized = normalized_text

        if normalized is None and variable.required:
            issues.append(
                ValidationIssue(
                    code="required_value_missing",
                    message="A required categorical value is missing.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
        values.append(normalized)

    return PreparedColumn(
        variable_name=variable.name,
        values=tuple(values),
        issues=tuple(issues),
    )


def prepare_numeric_column(snapshot: SourceSnapshot, variable: VariableSchema) -> PreparedColumn:
    """Validate numeric cells without locale guessing or non-finite values."""
    if variable.kind != VariableKind.NUMERIC:
        raise ValueError("prepare_numeric_column requires a numeric variable")

    try:
        column_index = snapshot.headers.index(variable.source_header)
    except ValueError:
        return PreparedColumn(
            variable_name=variable.name,
            values=(),
            issues=(
                ValidationIssue(
                    code="missing_configured_header",
                    message="A configured survey column is missing from the source.",
                    variable=variable.name,
                    source_row=snapshot.metadata.header_row,
                ),
            ),
        )

    values: list[Scalar] = []
    issues: list[ValidationIssue] = []
    missing_values = set(variable.missing_values)
    for offset, row in enumerate(snapshot.rows):
        source_row = snapshot.source_first_row + offset
        value = row[column_index] if column_index < len(row) else None
        is_missing = value is None or (
            isinstance(value, str)
            and (value.strip() if variable.trim_whitespace else value) in missing_values
        )
        if is_missing:
            normalized: Scalar = None
            if variable.required:
                issues.append(
                    ValidationIssue(
                        code="required_value_missing",
                        message="A required numeric value is missing.",
                        variable=variable.name,
                        source_row=source_row,
                    )
                )
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            normalized = None
            issues.append(
                ValidationIssue(
                    code="invalid_numeric_type",
                    message="A numeric value must be a finite number or an allowed missing value.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
        elif not math.isfinite(value):
            normalized = None
            issues.append(
                ValidationIssue(
                    code="non_finite_numeric",
                    message="A numeric value must be finite.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
        else:
            normalized = value
        values.append(normalized)

    return PreparedColumn(variable_name=variable.name, values=tuple(values), issues=tuple(issues))


def prepare_datetime_column(snapshot: SourceSnapshot, variable: VariableSchema) -> PreparedColumn:
    """Parse dates with the configured format and optional explicit timezone."""
    if variable.kind != VariableKind.DATETIME:
        raise ValueError("prepare_datetime_column requires a datetime variable")

    try:
        column_index = snapshot.headers.index(variable.source_header)
    except ValueError:
        return PreparedColumn(
            variable_name=variable.name,
            values=(),
            issues=(
                ValidationIssue(
                    code="missing_configured_header",
                    message="A configured survey column is missing from the source.",
                    variable=variable.name,
                    source_row=snapshot.metadata.header_row,
                ),
            ),
        )

    values: list[Scalar] = []
    issues: list[ValidationIssue] = []
    missing_values = set(variable.missing_values)
    timezone: ZoneInfo | None = None
    timezone_invalid = False
    if variable.timezone:
        try:
            timezone = ZoneInfo(variable.timezone)
        except ZoneInfoNotFoundError:
            timezone_invalid = True

    for offset, row in enumerate(snapshot.rows):
        source_row = snapshot.source_first_row + offset
        value = row[column_index] if column_index < len(row) else None
        candidate = value.strip() if isinstance(value, str) and variable.trim_whitespace else value
        is_missing = candidate is None or (
            isinstance(candidate, str) and candidate in missing_values
        )
        if is_missing:
            normalized: Scalar = None
            if variable.required:
                issues.append(
                    ValidationIssue(
                        code="required_value_missing",
                        message="A required datetime value is missing.",
                        variable=variable.name,
                        source_row=source_row,
                    )
                )
        elif not isinstance(candidate, str):
            normalized = None
            issues.append(
                ValidationIssue(
                    code="invalid_datetime_type",
                    message="A datetime value must be text matching the configured format.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
        elif timezone_invalid:
            normalized = None
            issues.append(
                ValidationIssue(
                    code="invalid_datetime_timezone",
                    message="The configured datetime timezone is unavailable.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
        else:
            try:
                parsed = datetime.strptime(candidate, variable.datetime_format or "")
            except ValueError:
                parsed = None
            if parsed is None:
                normalized = None
                issues.append(
                    ValidationIssue(
                        code="invalid_datetime_format",
                        message="A datetime value does not match the configured format.",
                        variable=variable.name,
                        source_row=source_row,
                    )
                )
            else:
                try:
                    if parsed.tzinfo is None and timezone is not None:
                        parsed = _localize_unambiguous(parsed, timezone)
                    elif parsed.tzinfo is not None and timezone is not None:
                        parsed = parsed.astimezone(timezone)
                except ValueError:
                    normalized = None
                    issues.append(
                        ValidationIssue(
                            code="ambiguous_or_nonexistent_datetime",
                            message=(
                                "A local datetime is ambiguous or does not exist in its timezone."
                            ),
                            variable=variable.name,
                            source_row=source_row,
                        )
                    )
                else:
                    normalized = parsed.isoformat()
        values.append(normalized)

    return PreparedColumn(variable_name=variable.name, values=tuple(values), issues=tuple(issues))


def _localize_unambiguous(value: datetime, timezone: ZoneInfo) -> datetime:
    candidates = [value.replace(tzinfo=timezone, fold=fold) for fold in (0, 1)]
    valid = [
        candidate
        for candidate in candidates
        if candidate.astimezone(ZoneInfo("UTC")).astimezone(timezone).replace(tzinfo=None) == value
    ]
    if not valid or (len(valid) == 2 and valid[0].utcoffset() != valid[1].utcoffset()):
        raise ValueError("local datetime cannot be localized unambiguously")
    return valid[0]
