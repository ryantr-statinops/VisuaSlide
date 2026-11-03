import math
from datetime import UTC, datetime

from visuaslide.config import SourceConfig, VariableSchema
from visuaslide.preparation import prepare_numeric_column
from visuaslide.snapshots import SourceSnapshot


def _snapshot(rows: tuple[tuple[object, ...], ...]) -> SourceSnapshot:
    return SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:B"),
        headers=("Score", "Comment"),
        rows=rows,
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def _variable(**kwargs: object) -> VariableSchema:
    return VariableSchema(
        name="score",
        source_header="Score",
        kind="numeric",
        **kwargs,
    )


def test_numeric_preparation_preserves_finite_values_and_allowed_missing() -> None:
    prepared = prepare_numeric_column(
        _snapshot(((2, ""), (3.5, ""), (None, ""), ("", ""))), _variable()
    )

    assert prepared.is_valid
    assert prepared.values == (2, 3.5, None, None)


def test_numeric_preparation_rejects_boolean_text_and_non_finite_values() -> None:
    prepared = prepare_numeric_column(
        _snapshot(((True, ""), ("1,25", ""), (math.nan, ""), (math.inf, ""))), _variable()
    )

    assert [issue.code for issue in prepared.issues] == [
        "invalid_numeric_type",
        "invalid_numeric_type",
        "non_finite_numeric",
        "non_finite_numeric",
    ]
    assert all(issue.source_row == index for index, issue in enumerate(prepared.issues, start=2))


def test_numeric_preparation_applies_required_and_declared_whitespace_policy() -> None:
    prepared = prepare_numeric_column(
        _snapshot((("  ", ""), (5, ""))),
        _variable(required=True, trim_whitespace=True),
    )

    assert prepared.values == (None, 5)
    assert [issue.code for issue in prepared.issues] == ["required_value_missing"]
