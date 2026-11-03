"""Structural validation of the single source tab snapshot."""

from __future__ import annotations

from collections import Counter

from visuaslide.config import SurveySchema
from visuaslide.exceptions import DataValidationError
from visuaslide.models import ValidationIssue, ValidationReport
from visuaslide.snapshots import SourceSnapshot


def validate_snapshot_structure(
    snapshot: SourceSnapshot,
    schema: SurveySchema,
    *,
    snapshot_id: str,
) -> ValidationReport:
    """Check headers, source mappings, empty tables, and row widths."""
    dataset_issues: list[ValidationIssue] = []
    for header in snapshot.headers:
        if not header.strip():
            dataset_issues.append(
                ValidationIssue(
                    code="blank_header",
                    message="The source table contains a blank column header.",
                    source_row=snapshot.metadata.header_row,
                )
            )

    duplicate_headers = [header for header, count in Counter(snapshot.headers).items() if count > 1]
    for _header in duplicate_headers:
        dataset_issues.append(
            ValidationIssue(
                code="duplicate_header",
                message="The source table contains duplicate column headers.",
                source_row=snapshot.metadata.header_row,
            )
        )

    actual_headers = set(snapshot.headers)
    for variable in schema.variables:
        if variable.source_header not in actual_headers:
            dataset_issues.append(
                ValidationIssue(
                    code="missing_configured_header",
                    message="A configured survey column is missing from the source.",
                    variable=variable.name,
                    source_row=snapshot.metadata.header_row,
                )
            )

    if not snapshot.rows or not any(not _is_blank_row(row) for row in snapshot.rows):
        dataset_issues.append(
            ValidationIssue(
                code="empty_input",
                message="The source table has no nonblank response rows.",
            )
        )

    blank_rows = 0
    accepted_rows = 0
    invalid_rows = 0
    row_issues: list[ValidationIssue] = []
    for offset, row in enumerate(snapshot.rows):
        source_row = snapshot.source_first_row + offset
        if _is_blank_row(row):
            blank_rows += 1
            continue
        if len(row) > len(snapshot.headers):
            invalid_rows += 1
            row_issues.append(
                ValidationIssue(
                    code="row_width_exceeds_header",
                    message="A source row contains more cells than the header row.",
                    source_row=source_row,
                )
            )
        else:
            accepted_rows += 1

    return ValidationReport(
        snapshot_id=snapshot_id,
        input_rows=len(snapshot.rows),
        blank_rows=blank_rows,
        accepted_rows=accepted_rows,
        invalid_rows=invalid_rows,
        issues=tuple(row_issues),
        dataset_issues=tuple(dataset_issues),
    )


def _is_blank_row(row: tuple[object, ...]) -> bool:
    return all(value is None or (isinstance(value, str) and value == "") for value in row)


def normalize_trailing_cells(snapshot: SourceSnapshot) -> tuple[tuple[object, ...], ...]:
    """Pad omitted trailing cells and reject rows wider than their header."""
    width = len(snapshot.headers)
    normalized: list[tuple[object, ...]] = []
    for offset, row in enumerate(snapshot.rows):
        if len(row) > width:
            source_row = snapshot.source_first_row + offset
            raise DataValidationError(
                f"Source row {source_row} contains more cells than the header row."
            )
        normalized.append(row + (None,) * (width - len(row)))
    return tuple(normalized)
