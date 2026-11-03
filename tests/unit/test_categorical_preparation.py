from datetime import UTC, datetime

import pytest

from visuaslide.config import SourceConfig, VariableSchema
from visuaslide.preparation import prepare_categorical_column
from visuaslide.snapshots import SourceSnapshot


def _snapshot(rows: tuple[tuple[object, ...], ...]) -> SourceSnapshot:
    return SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:B"),
        headers=("Answer", "Comment"),
        rows=rows,
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def _variable(**kwargs: object) -> VariableSchema:
    return VariableSchema(
        name="answer",
        source_header="Answer",
        kind="categorical",
        categories=("yes", "no"),
        **kwargs,
    )


def test_categorical_preparation_preserves_configured_values_duplicates_and_missing() -> None:
    snapshot = _snapshot((("yes", "same"), ("yes", "same"), ("", ""), (None, None)))

    prepared = prepare_categorical_column(snapshot, _variable())

    assert prepared.is_valid
    assert prepared.values == ("yes", "yes", None, None)


def test_categorical_preparation_rejects_unknown_category_without_echoing_value() -> None:
    prepared = prepare_categorical_column(_snapshot((("private answer", ""),)), _variable())

    assert not prepared.is_valid
    assert prepared.issues[0].code == "unknown_category"
    assert prepared.issues[0].source_row == 2
    assert "private answer" not in prepared.issues[0].message


def test_categorical_preparation_only_trims_when_declared() -> None:
    raw = _snapshot(((" yes ", ""),))

    assert not prepare_categorical_column(raw, _variable()).is_valid
    assert prepare_categorical_column(raw, _variable(trim_whitespace=True)).values == ("yes",)


def test_categorical_preparation_reports_required_missing_values() -> None:
    prepared = prepare_categorical_column(_snapshot((("", ""),)), _variable(required=True))

    assert not prepared.is_valid
    assert prepared.issues[0].code == "required_value_missing"


def test_categorical_preparation_rejects_non_text_and_wrong_variable_kind() -> None:
    prepared = prepare_categorical_column(_snapshot(((1, ""),)), _variable())
    assert prepared.issues[0].code == "invalid_categorical_type"

    numeric = VariableSchema(name="score", source_header="Answer", kind="numeric")
    with pytest.raises(ValueError, match="categorical"):
        prepare_categorical_column(_snapshot((("yes", ""),)), numeric)
