import json
from datetime import UTC, datetime
from pathlib import Path

from visuaslide import AnalysisResult, RunResult, SurveyProject, ValidationReport
from visuaslide.exceptions import PublishingError, TransientAdapterError
from visuaslide.models import RunStatus
from visuaslide.publisher import FakeReportPublisher
from visuaslide.retry import RetryPolicy
from visuaslide.snapshots import SourceSnapshot
from visuaslide.testing import FixtureSource

ROOT = Path(__file__).parents[2]


def _project(tmp_path: Path) -> tuple[SurveyProject, FakeReportPublisher]:
    config_text = (ROOT / "examples/survey.example.toml").read_text("utf-8")
    config_text = config_text.replace(
        "REPLACE_WITH_YOUR_GOOGLE_SHEETS_ID", "synthetic-survey"
    ).replace(
        'project_dir = "../.visuaslide/example-run"',
        f'project_dir = "{tmp_path.as_posix()}/runtime"',
    )
    config_path = tmp_path / "survey.toml"
    config_path.write_text(config_text, encoding="utf-8")
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text("utf-8"))
    config_project = SurveyProject.from_toml(config_path)
    snapshot = SourceSnapshot.capture(
        config_project.config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(tuple(row) for row in fixture["rows"]),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    publisher = FakeReportPublisher()
    project = SurveyProject.from_toml(
        config_path,
        source=FixtureSource(snapshot),
        publisher=publisher,
    )
    return project, publisher


def test_public_sdk_supports_dry_run_publish_replay_and_run_inspection(tmp_path) -> None:
    project, publisher = _project(tmp_path)

    dry_run = project.refresh(dry_run=True)
    assert isinstance(dry_run, RunResult)
    assert dry_run.status == RunStatus.READY
    assert dry_run.stage == "dry_run_complete"
    assert publisher.objects == {}

    published = project.refresh()
    assert published.status == RunStatus.COMPLETED
    assert published.analysis is not None
    assert isinstance(published.analysis, AnalysisResult)
    assert len(publisher.objects) > 0

    inspected = project.inspect_run(published.run_id)
    assert inspected.status == RunStatus.COMPLETED
    assert inspected.analysis == published.analysis
    assert published.snapshot_id is not None
    assert isinstance(project.validate(published.snapshot_id), ValidationReport)
    assert project.analyze(published.snapshot_id).tables == published.analysis.tables


def test_sdk_retries_transient_publisher_failure_but_keeps_one_output_set(tmp_path) -> None:
    project, fake_publisher = _project(tmp_path)
    attempts = 0
    delays = []

    class FlakyPublisher:
        def __init__(self) -> None:
            self.mapping = fake_publisher.mapping

        def publish_step(self, step, content, plan):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TransientAdapterError("temporary publisher outage")
            result = fake_publisher.publish_step(step, content, plan)
            self.mapping = fake_publisher.mapping
            return result

    project.publisher = FlakyPublisher()
    project.retry_policy = RetryPolicy(max_attempts=2, initial_backoff_seconds=0.05)
    project.sleep = delays.append

    result = project.refresh()

    assert result.status == RunStatus.COMPLETED
    assert attempts == 4
    assert delays == [0.05]
    assert len(fake_publisher.objects) == 17


def test_sdk_records_partial_publish_checkpoint_and_never_reports_completion(tmp_path) -> None:
    project, _ = _project(tmp_path)

    class FailsDuringCharts(FakeReportPublisher):
        def publish_step(self, step, content, plan):
            if step == "charts":
                raise PublishingError("simulated chart failure")
            return super().publish_step(step, content, plan)

    publisher = FailsDuringCharts()
    project.publisher = publisher
    try:
        project.refresh()
    except PublishingError as exc:
        assert str(exc) == "simulated chart failure"
    else:
        raise AssertionError("partial publishing should raise")

    run_paths = list((tmp_path / "runtime" / "runs").glob("*.json"))
    manifest = project._runs.load(run_paths[0].stem)
    assert manifest.status == RunStatus.FAILED
    assert manifest.stage == "publish_failed"
    assert "workbook" in manifest.completed_steps
    assert "charts" not in manifest.completed_steps
    assert "slides" not in manifest.completed_steps
    assert len(publisher.workbook_objects) == 4
    assert publisher.objects == {}
