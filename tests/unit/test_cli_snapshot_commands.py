import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from visuaslide.cli import app
from visuaslide.config import load_config
from visuaslide.runs import RunStore
from visuaslide.snapshots import SourceSnapshot
from visuaslide.storage import SnapshotStore

ROOT = Path(__file__).parents[2]


def _project_files(tmp_path: Path):
    config_text = (ROOT / "examples/survey.example.toml").read_text("utf-8")
    config_text = config_text.replace(
        "REPLACE_WITH_YOUR_GOOGLE_SHEETS_ID", "synthetic-survey"
    ).replace(
        'project_dir = "../.visuaslide/example-run"',
        f'project_dir = "{tmp_path.as_posix()}/runtime"',
    )
    config_path = tmp_path / "survey.toml"
    config_path.write_text(config_text, encoding="utf-8")
    config = load_config(config_path)
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text("utf-8"))
    snapshot = SourceSnapshot.capture(
        config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(tuple(row) for row in fixture["rows"]),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    stored = SnapshotStore(config.project_dir).save(snapshot)
    run = RunStore(config.project_dir).create(config)
    return config_path, stored.snapshot_id, run.run_id


def test_cli_validates_analyzes_and_inspects_stored_runs(tmp_path) -> None:
    config_path, snapshot_id, run_id = _project_files(tmp_path)
    runner = CliRunner()

    validated = runner.invoke(
        app,
        ["validate", "--config", str(config_path), "--snapshot-id", snapshot_id],
    )
    analyzed = runner.invoke(
        app,
        ["analyze", "--config", str(config_path), "--snapshot-id", snapshot_id],
    )
    inspected = runner.invoke(
        app,
        ["inspect-run", "--config", str(config_path), "--run-id", run_id],
    )

    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["is_valid"] is True
    assert analyzed.exit_code == 0, analyzed.output
    assert json.loads(analyzed.output)["snapshot_id"] == snapshot_id
    assert inspected.exit_code == 0, inspected.output
    assert json.loads(inspected.output)["run_id"] == run_id


def test_cli_reports_validation_failure_with_nonzero_exit_and_safe_json(tmp_path) -> None:
    config_path, snapshot_id, _ = _project_files(tmp_path)
    config = load_config(config_path)
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text("utf-8"))
    rows = [tuple(row) for row in fixture["rows"]]
    rows[0] = (rows[0][0], "private unexpected value", *rows[0][2:])
    bad = SourceSnapshot.capture(
        config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(rows),
        acquired_at=datetime(2026, 11, 4, tzinfo=UTC),
    )
    bad_id = SnapshotStore(config.project_dir).save(bad).snapshot_id

    result = CliRunner().invoke(
        app,
        ["validate", "--config", str(config_path), "--snapshot-id", bad_id],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["is_valid"] is False
    assert "private unexpected value" not in result.output


def test_cli_refresh_supports_fixture_dry_run_and_fake_publish(tmp_path) -> None:
    config_path, _, _ = _project_files(tmp_path)
    fixture_path = ROOT / "tests/fixtures/synthetic_responses.json"
    runner = CliRunner()

    dry_run = runner.invoke(
        app,
        [
            "refresh",
            "--config",
            str(config_path),
            "--fixture-json",
            str(fixture_path),
            "--dry-run",
        ],
    )
    published = runner.invoke(
        app,
        ["refresh", "--config", str(config_path), "--fixture-json", str(fixture_path)],
    )

    assert dry_run.exit_code == 0, dry_run.output
    assert json.loads(dry_run.output)["stage"] == "dry_run_complete"
    assert json.loads(dry_run.output)["status"] == "ready"
    assert published.exit_code == 0, published.output
    assert json.loads(published.output)["stage"] == "published"
    assert json.loads(published.output)["status"] == "completed"


def test_cli_google_refresh_requires_local_authorization(tmp_path) -> None:
    config_path, _, _ = _project_files(tmp_path)

    result = CliRunner().invoke(app, ["refresh", "--config", str(config_path)])

    assert result.exit_code == 2
    assert "Google token is unavailable" in result.output
