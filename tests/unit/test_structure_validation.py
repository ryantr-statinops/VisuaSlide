from datetime import UTC, datetime

import pytest

from visuaslide.config import SourceConfig, SurveySchema, VariableSchema
from visuaslide.exceptions import DataValidationError
from visuaslide.snapshots import SourceSnapshot
from visuaslide.validation import normalize_trailing_cells, validate_snapshot_structure


def _schema() -> SurveySchema:
    return SurveySchema(
        variables=(
            VariableSchema(
                name="answer",
                source_header="Answer",
                kind="categorical",
                categories=("yes", "no"),
            ),
        )
    )


def _snapshot(headers: tuple[str, ...], rows: tuple[tuple[object, ...], ...]) -> SourceSnapshot:
    return SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:D"),
        headers=headers,
        rows=rows,
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def test_structure_validation_counts_blank_rows_and_accepts_trailing_empty_cells() -> None:
    report = validate_snapshot_structure(
        _snapshot(("Response ID", "Answer", "Extra"), (("r1", "yes"), ("", "", ""))),
        _schema(),
        snapshot_id="a" * 64,
    )

    assert report.is_valid
    assert (report.input_rows, report.blank_rows, report.accepted_rows, report.invalid_rows) == (
        2,
        1,
        1,
        0,
    )


def test_normalize_trailing_cells_pads_rows_omitted_by_google_api() -> None:
    snapshot = _snapshot(("Response ID", "Answer", "Comment"), (("r1", "yes"),))

    assert normalize_trailing_cells(snapshot) == (("r1", "yes", None),)


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        (("Response ID", "", "Extra"), "blank_header"),
        (("Response ID", "Answer", "Answer"), "duplicate_header"),
        (("Response ID", "Other"), "missing_configured_header"),
    ],
)
def test_structure_validation_reports_invalid_headers_without_raw_values(
    headers: tuple[str, ...], expected_code: str
) -> None:
    report = validate_snapshot_structure(
        _snapshot(headers, (("r1", "private response"),)),
        _schema(),
        snapshot_id="b" * 64,
    )

    assert not report.is_valid
    assert expected_code in {issue.code for issue in report.dataset_issues}
    assert all("private response" not in issue.message for issue in report.dataset_issues)


def test_structure_validation_rejects_rows_longer_than_header_at_source_position() -> None:
    report = validate_snapshot_structure(
        _snapshot(("Response ID", "Answer"), (("r1", "yes"), ("r2", "no", "extra"))),
        _schema(),
        snapshot_id="c" * 64,
    )

    assert not report.is_valid
    assert report.invalid_rows == 1
    assert report.issues[0].source_row == 3

    with pytest.raises(DataValidationError, match="Source row 3"):
        normalize_trailing_cells(
            _snapshot(("Response ID", "Answer"), (("r1", "yes"), ("r2", "no", "extra")))
        )


@pytest.mark.parametrize("rows", [(), (("", ""), (None, None))])
def test_structure_validation_rejects_empty_source_tables(
    rows: tuple[tuple[object, ...], ...],
) -> None:
    report = validate_snapshot_structure(
        _snapshot(("Response ID", "Answer"), rows),
        _schema(),
        snapshot_id="d" * 64,
    )

    assert not report.is_valid
    assert "empty_input" in {issue.code for issue in report.dataset_issues}
