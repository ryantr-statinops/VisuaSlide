"""Schema-driven preparation of survey columns."""

from __future__ import annotations

import math
from dataclasses import dataclass

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
