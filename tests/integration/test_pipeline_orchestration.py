import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visuaslide.config import load_config
from visuaslide.exceptions import ConfigurationError
from visuaslide.models import RunStatus
from visuaslide.pipeline import SurveyRunner
from visuaslide.runs import RunStore
from visuaslide.snapshots import SourceSnapshot
from visuaslide.testing import FixtureSource

ROOT = Path(__file__).parents[2]


def _runner(tmp_path: Path, *, invalid: bool = False) -> SurveyRunner:
    config = load_config(ROOT / "examples/survey.example.toml")
    config = config.model_copy(
        update={
            "source": config.source.model_copy(update={"spreadsheet_id": "synthetic-survey"}),
            "project_dir": tmp_path,
        }
    )
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text())
    rows = [tuple(row) for row in fixture["rows"]]
    if invalid:
        rows[0] = (rows[0][0], "Unexpected", *rows[0][2:])
    snapshot = SourceSnapshot.capture(
        config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(rows),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    return SurveyRunner(config, FixtureSource(snapshot))


def test_runner_tracks_refresh_stages_and_persists_safe_results(tmp_path) -> None:
    runner = _runner(tmp_path)

    result = runner.refresh()
    manifest = RunStore(tmp_path).load(result.run_id)

    assert result.status == RunStatus.READY
    assert result.stage == "analysis_complete"
    assert result.snapshot_id
    assert result.analysis is not None
    assert result.analysis.accepted_rows == 5
    assert manifest.completed_steps == ("snapshot", "validation", "dataset", "analysis")
    assert (tmp_path / "datasets" / f"{result.snapshot_id}.parquet").is_file()
    assert (tmp_path / "analyses" / f"{result.run_id}.json").is_file()
    assert (tmp_path / "reports" / f"{result.run_id}.validation.json").is_file()


def test_runner_saves_invalid_source_snapshot_and_stops_before_dataset(tmp_path) -> None:
    result = _runner(tmp_path, invalid=True).refresh()
    manifest = RunStore(tmp_path).load(result.run_id)

    assert result.status == RunStatus.VALIDATION_FAILED
    assert result.error_code == "data_validation_failed"
    assert result.snapshot_id
    assert manifest.completed_steps == ("snapshot", "validation")
    assert (tmp_path / "snapshots" / f"{result.snapshot_id}.json").is_file()
    assert not list((tmp_path / "datasets").glob("*.parquet"))
    report_text = (tmp_path / "reports" / f"{result.run_id}.validation.json").read_text()
    assert "Unexpected" not in report_text


def test_runner_records_safe_failure_state_when_source_read_raises(tmp_path) -> None:
    runner = _runner(tmp_path)

    class BrokenSource:
        def read(self, source):
            raise RuntimeError("secret response payload")

    runner.source = BrokenSource()
    with pytest.raises(RuntimeError, match="secret response payload"):
        runner.refresh()

    manifests = list((tmp_path / "runs").glob("*.json"))
    assert len(manifests) == 1
    persisted = manifests[0].read_text()
    assert '"status":"failed"' in persisted
    assert '"error_code":"pipeline_failed"' in persisted
    assert "secret response payload" not in persisted


def test_snapshot_replay_validates_and_analyzes_without_reading_source(tmp_path) -> None:
    runner = _runner(tmp_path)
    original = runner.refresh()
    assert original.snapshot_id is not None

    class MustNotReadSource:
        def read(self, source):
            raise AssertionError("snapshot replay attempted to read its source")

    runner.source = MustNotReadSource()
    validation = runner.validate_snapshot(original.snapshot_id)
    replay = runner.analyze_snapshot(original.snapshot_id)

    assert validation.is_valid
    assert replay.status == RunStatus.READY
    assert replay.snapshot_id == original.snapshot_id
    assert replay.analysis is not None
    assert replay.analysis.tables == original.analysis.tables


def test_snapshot_replay_rejects_a_changed_effective_configuration(tmp_path) -> None:
    runner = _runner(tmp_path)
    original = runner.refresh()
    assert original.snapshot_id is not None
    changed_config = runner.config.model_copy(
        update={"report": runner.config.report.model_copy(update={"title": "Changed title"})}
    )
    changed_runner = SurveyRunner(changed_config, runner.source)

    with pytest.raises(ConfigurationError, match="configuration recorded"):
        changed_runner.analyze_snapshot(original.snapshot_id)
