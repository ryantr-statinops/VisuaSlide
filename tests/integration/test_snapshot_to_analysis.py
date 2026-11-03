import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from visuaslide.analysis import calculate_crosstab, calculate_frequency, calculate_numeric_summary
from visuaslide.config import load_config
from visuaslide.datasets import DatasetStore
from visuaslide.exceptions import StorageError
from visuaslide.models import ValidationReport
from visuaslide.preparation import (
    prepare_categorical_column,
    prepare_datetime_column,
    prepare_numeric_column,
)
from visuaslide.snapshots import SourceSnapshot
from visuaslide.storage import SnapshotStore
from visuaslide.testing import FixtureSource
from visuaslide.validation import normalize_trailing_cells, validate_snapshot_structure

ROOT = Path(__file__).parents[2]


def _fixture_snapshot(*, unknown_category: bool = False) -> SourceSnapshot:
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text())
    config = load_config(ROOT / "examples/survey.example.toml")
    source = config.source.model_copy(update={"spreadsheet_id": "synthetic-survey"})
    rows = [tuple(row) for row in fixture["rows"]]
    if unknown_category:
        rows[0] = (rows[0][0], "Other year", *rows[0][2:])
    return SourceSnapshot.capture(
        source,
        headers=tuple(fixture["headers"]),
        rows=tuple(rows),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def _prepare(snapshot: SourceSnapshot, snapshot_id: str):
    config = load_config(ROOT / "examples/survey.example.toml")
    source = config.source.model_copy(update={"spreadsheet_id": snapshot.metadata.spreadsheet_id})
    assert FixtureSource(snapshot).read(source) == snapshot
    structural = validate_snapshot_structure(
        snapshot, config.survey_schema, snapshot_id=snapshot_id
    )
    prepared = {}
    issues = list(structural.issues)
    for variable in config.survey_schema.variables:
        if variable.kind.value == "categorical":
            column = prepare_categorical_column(snapshot, variable)
            prepared[variable.name] = column.values
            issues.extend(column.issues)
        elif variable.kind.value == "numeric":
            column = prepare_numeric_column(snapshot, variable)
            prepared[variable.name] = column.values
            issues.extend(column.issues)
        elif variable.kind.value == "datetime":
            column = prepare_datetime_column(snapshot, variable)
            prepared[variable.name] = column.values
            issues.extend(column.issues)
        else:
            column_index = snapshot.headers.index(variable.source_header)
            prepared[variable.name] = tuple(
                row[column_index] if column_index < len(row) else None for row in snapshot.rows
            )

    invalid_source_rows = {issue.source_row for issue in issues if issue.source_row is not None}
    invalid_data_rows = len(invalid_source_rows - {None})
    report = ValidationReport(
        snapshot_id=snapshot_id,
        input_rows=structural.input_rows,
        blank_rows=structural.blank_rows,
        accepted_rows=max(structural.accepted_rows - invalid_data_rows, 0),
        invalid_rows=structural.invalid_rows + invalid_data_rows,
        issues=tuple(issues),
        dataset_issues=structural.dataset_issues,
    )
    nonblank_indices = [
        index
        for index, row in enumerate(normalize_trailing_cells(snapshot))
        if not all(value is None or value == "" for value in row)
    ]
    frame = pd.DataFrame(
        {name: [values[index] for index in nonblank_indices] for name, values in prepared.items()}
    )
    return config, report, frame


def test_snapshot_to_analysis_matches_independent_reference(tmp_path) -> None:
    snapshot = _fixture_snapshot()
    raw_store = SnapshotStore(tmp_path / "snapshots")
    stored = raw_store.save(snapshot)
    replayed = raw_store.load(stored.snapshot_id).snapshot
    config, report, frame = _prepare(replayed, stored.snapshot_id)

    assert report.is_valid
    assert frame.loc[0, "response_id"] == "r001"
    assert frame.loc[0, "score"] == 8
    DatasetStore(tmp_path / "datasets").save(stored.snapshot_id, frame, report)
    restored = DatasetStore(tmp_path / "datasets").load(stored.snapshot_id)
    expected = json.loads((ROOT / "tests/fixtures/expected_summary.json").read_text())
    specifications = {spec.id: spec for spec in config.analysis.specifications}
    variables = {var.name: var for var in config.survey_schema.variables}

    years = calculate_frequency(
        restored, variables["study_year"], specifications["study_year_counts"]
    )
    scores = calculate_numeric_summary(
        restored, variables["score"], specifications["score_summary"]
    )
    tool_use = calculate_frequency(
        restored, variables["uses_tool"], specifications["tool_use_rate"]
    )
    cross = calculate_crosstab(
        restored,
        variables["study_year"],
        variables["uses_tool"],
        specifications["year_by_tool"],
    )

    assert {row[0]: row[1] for row in years.rows} == expected["study_year_counts"]
    assert {row[0]: row[1] for row in scores.rows}["mean"] == expected["score_mean"]
    assert (
        abs(
            {row[0]: row[1] for row in scores.rows}["sample_stddev"]
            - expected["score_sample_standard_deviation"]
        )
        < 1e-12
    )
    assert [row[1] for row in tool_use.rows] == [3, 1]
    assert {(row[0], row[1]): row[2] for row in cross.rows if row[2]} == {
        ("Year 1", "Yes"): 2,
        ("Year 2", "No"): 1,
        ("Year 3", "Yes"): 1,
    }


def test_snapshot_with_invalid_category_is_saved_but_never_becomes_dataset(tmp_path) -> None:
    snapshot = _fixture_snapshot(unknown_category=True)
    stored = SnapshotStore(tmp_path / "snapshots").save(snapshot)
    _, report, frame = _prepare(stored.snapshot, stored.snapshot_id)

    assert not report.is_valid
    assert any(issue.code == "unknown_category" for issue in report.issues)
    with pytest.raises(StorageError, match="validation errors"):
        DatasetStore(tmp_path / "datasets").save(stored.snapshot_id, frame, report)
    assert not list((tmp_path / "datasets").glob("*.parquet"))
