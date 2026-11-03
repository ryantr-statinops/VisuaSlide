from datetime import UTC, datetime

from visuaslide.config import SourceConfig, VariableSchema
from visuaslide.preparation import prepare_datetime_column
from visuaslide.snapshots import SourceSnapshot


def _snapshot(rows: tuple[tuple[object, ...], ...]) -> SourceSnapshot:
    return SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:B"),
        headers=("Collected at", "Comment"),
        rows=rows,
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def _variable(**kwargs: object) -> VariableSchema:
    values = {
        "name": "collected_at",
        "source_header": "Collected at",
        "kind": "datetime",
        "datetime_format": "%d/%m/%Y",
        **kwargs,
    }
    return VariableSchema(**values)


def test_datetime_preparation_uses_declared_format_and_keeps_naive_without_timezone() -> None:
    prepared = prepare_datetime_column(_snapshot((("03/11/2026", ""),)), _variable())

    assert prepared.is_valid
    assert prepared.values == ("2026-11-03T00:00:00",)


def test_datetime_preparation_applies_only_configured_timezone() -> None:
    variable = _variable(datetime_format="%Y-%m-%dT%H:%M:%S%z", timezone="Asia/Ho_Chi_Minh")
    prepared = prepare_datetime_column(_snapshot((("2026-11-03T12:00:00+0000", ""),)), variable)

    assert prepared.values == ("2026-11-03T19:00:00+07:00",)


def test_datetime_preparation_rejects_mismatch_type_and_ambiguous_local_time() -> None:
    variable = _variable(datetime_format="%Y-%m-%d %H:%M", timezone="Europe/Berlin")
    prepared = prepare_datetime_column(
        _snapshot((("2026-10-25 02:30", ""), ("not a date", ""), (42, ""))), variable
    )

    assert [issue.code for issue in prepared.issues] == [
        "ambiguous_or_nonexistent_datetime",
        "invalid_datetime_format",
        "invalid_datetime_type",
    ]
    assert [issue.source_row for issue in prepared.issues] == [2, 3, 4]


def test_datetime_preparation_preserves_allowed_missing_and_reports_required() -> None:
    prepared = prepare_datetime_column(
        _snapshot((("", "response exists"),)), _variable(required=True)
    )

    assert prepared.values == (None,)
    assert prepared.issues[0].code == "required_value_missing"
