import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest
from typer.testing import CliRunner

from visuaslide import SurveyProject
from visuaslide.cli import app
from visuaslide.config import PercentageDenominator
from visuaslide.datasets import DatasetStore
from visuaslide.models import RunStatus, ValidationReport
from visuaslide.publisher import FakeReportPublisher
from visuaslide.storage import SnapshotStore
from visuaslide.testing import FixtureSource


def test_hand_calculated_results_and_immutable_raw_values(multiselect_case):
    config, snapshot = multiselect_case
    project = SurveyProject(config, source=FixtureSource(snapshot))
    result = project.refresh(dry_run=True)
    assert result.status == RunStatus.READY
    tables = {table.analysis_id: table for table in result.analysis.tables}
    assert tables["certificate_counts"].rows == (
        ("IELTS", 2, 2, 2, 1.0),
        ("TOEIC", 0, 0, 2, 0.0),
        ("APTIS", 0, 0, 2, 0.0),
        ("PET (Cambridge)", 1, 1, 2, 0.5),
    )
    assert [row[3] for row in tables["wanted_info_counts"].rows] == [3, 3]
    assert [row[4] for row in tables["wanted_info_counts"].rows] == [2 / 3, 1 / 3]
    assert len(tables["faculty_counts"].rows) == 13
    assert SnapshotStore(config.project_dir).load(result.snapshot_id).snapshot == snapshot
    replay = project.analyze(result.snapshot_id)
    assert replay.tables == result.analysis.tables
    frame = DatasetStore(config.project_dir / "datasets").load(result.snapshot_id)
    assert frame["certificates"].dtype == pd.ArrowDtype(pa.list_(pa.string()))
    assert frame["certificates"].iloc[0] == ["IELTS", "PET (Cambridge)"]
    assert pd.isna(frame["certificates"].iloc[2])


@pytest.mark.parametrize(
    ("policy", "expected_denominator"),
    [(PercentageDenominator.NON_MISSING, 0), (PercentageDenominator.ALL_RESPONSES, 3)],
)
def test_all_missing_multiselect_columns_preserve_list_type_and_denominators(
    multiselect_case, policy, expected_denominator
):
    config, snapshot = multiselect_case
    specifications = tuple(
        spec.model_copy(update={"denominator": policy}) if spec.id == "certificate_counts" else spec
        for spec in config.analysis.specifications
    )
    config = config.model_copy(
        update={"analysis": config.analysis.model_copy(update={"specifications": specifications})}
    )
    snapshot = snapshot.model_copy(
        update={"rows": tuple((*row[:2], None, *row[3:]) for row in snapshot.rows)}
    )
    project = SurveyProject(config, source=FixtureSource(snapshot))
    result = project.refresh(dry_run=True)
    table = next(
        table for table in result.analysis.tables if table.analysis_id == "certificate_counts"
    )
    assert all(row[1:4] == (0, 0, expected_denominator) for row in table.rows)
    assert all(row[4] == (None if expected_denominator == 0 else 0.0) for row in table.rows)
    frame = DatasetStore(config.project_dir / "datasets").load(result.snapshot_id)
    assert frame["certificates"].dtype == pd.ArrowDtype(pa.list_(pa.string()))
    assert project.analyze(result.snapshot_id).tables == result.analysis.tables


@pytest.mark.parametrize(("column", "invalid"), [(2, "IELTS, Unconfigured"), (4, 9), (4, 2.5)])
def test_invalid_answers_block_publication_and_preserve_snapshot(multiselect_case, column, invalid):
    config, snapshot = multiselect_case
    row = list(snapshot.rows[0])
    row[column] = invalid
    snapshot = snapshot.model_copy(update={"rows": (tuple(row), *snapshot.rows[1:])})
    publisher = FakeReportPublisher()
    result = SurveyProject(config, source=FixtureSource(snapshot), publisher=publisher).refresh()
    assert result.status == RunStatus.VALIDATION_FAILED
    assert result.analysis is None
    assert publisher.objects == publisher.workbook_objects == {}
    assert SnapshotStore(config.project_dir).load(result.snapshot_id).snapshot == snapshot
    report = json.loads(
        (config.project_dir / "reports" / f"{result.run_id}.validation.json").read_bytes()
    )
    assert report["invalid_rows"] == 1
    assert "Unconfigured" not in json.dumps(report)


def test_scalar_dataset_compatibility(tmp_path):
    frame = pd.DataFrame({"number": [1, 2], "label": ["A", None]})
    validation = ValidationReport(
        snapshot_id="a" * 64, input_rows=2, blank_rows=0, accepted_rows=2, invalid_rows=0
    )
    store = DatasetStore(tmp_path)
    store.save(validation.snapshot_id, frame, validation)
    pd.testing.assert_frame_equal(store.load(validation.snapshot_id), frame)
    store.save(validation.snapshot_id, frame, validation)


def test_cli_uses_numeric_and_multiselect_validation(multiselect_case, tmp_path):
    _, snapshot = multiselect_case
    root = Path(__file__).parents[2]
    toml = (root / "examples/multiselect.example.toml").read_text(encoding="utf-8")
    config_path = tmp_path / "survey.toml"
    config_path.write_text(
        toml.replace("../.visuaslide/multiselect-example", (tmp_path / "runtime").as_posix()),
        encoding="utf-8",
    )
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps({"headers": snapshot.headers, "rows": [(*snapshot.rows[0][:4], 9)]}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["refresh", "--config", str(config_path), "--fixture-json", str(fixture)]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "validation_failed"
