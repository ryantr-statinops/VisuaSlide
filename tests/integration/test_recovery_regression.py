"""End-to-end idempotency and recovery regressions for the offline pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visuaslide import SurveyProject
from visuaslide.exceptions import PublishingError
from visuaslide.models import RunStatus
from visuaslide.publisher import FakeReportPublisher
from visuaslide.snapshots import SourceSnapshot
from visuaslide.testing import FixtureSource

ROOT = Path(__file__).parents[2]


def _project(tmp_path: Path) -> tuple[SurveyProject, FakeReportPublisher, SourceSnapshot]:
    config_text = (ROOT / "examples/survey.example.toml").read_text("utf-8")
    config_text = config_text.replace(
        "REPLACE_WITH_YOUR_GOOGLE_SHEETS_ID", "synthetic-survey"
    ).replace(
        'project_dir = "../.visuaslide/example-run"',
        f'project_dir = "{tmp_path.as_posix()}/runtime"',
    )
    config_path = tmp_path / "survey.toml"
    config_path.write_text(config_text, encoding="utf-8")
    config = SurveyProject.from_toml(config_path).config
    fixture = json.loads((ROOT / "tests/fixtures/synthetic_responses.json").read_text("utf-8"))
    snapshot = SourceSnapshot.capture(
        config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(tuple(row) for row in fixture["rows"]),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    publisher = FakeReportPublisher()
    project = SurveyProject(config, source=FixtureSource(snapshot), publisher=publisher)
    return project, publisher, snapshot


def test_refresh_reconciles_added_updated_and_deleted_responses(tmp_path) -> None:
    project, publisher, original_snapshot = _project(tmp_path)
    first = project.refresh()
    assert first.analysis is not None
    original_analysis = first.analysis
    original_snapshot_id = first.snapshot_id
    original_ids = {entry.object_key: entry.object_id for entry in publisher.mapping.entries}

    changed_rows = list(original_snapshot.rows)
    changed_rows.pop(0)  # Delete one response.
    changed_rows[0] = (*changed_rows[0][:3], 42, *changed_rows[0][4:])  # Edit one response.
    changed_rows.extend(
        (
            ("r006", "Year 2", "Yes", 19, "2026-10-10 13:00", "added response"),
            ("r007", "Year 3", "No", 20, "2026-10-10 14:00", "added response"),
        )
    )
    revised_snapshot = SourceSnapshot.capture(
        project.config.source,
        headers=original_snapshot.headers,
        rows=tuple(changed_rows),
        acquired_at=datetime(2026, 11, 4, tzinfo=UTC),
    )
    project.source = FixtureSource(revised_snapshot)
    project._runner.source = project.source

    second = project.refresh()
    assert second.analysis is not None
    revised_ids = {entry.object_key: entry.object_id for entry in publisher.mapping.entries}

    assert first.status == second.status == RunStatus.COMPLETED
    assert first.snapshot_id == original_snapshot_id
    assert second.snapshot_id != original_snapshot_id
    assert original_analysis.accepted_rows == 5
    assert second.analysis.accepted_rows == 6
    assert second.analysis.snapshot_id == second.snapshot_id
    assert revised_ids == original_ids
    assert len(publisher.objects) == 17
    assert len(publisher.workbook_objects) == 7

    # Replaying the original snapshot still returns the original result.
    assert project.analyze(original_snapshot_id).accepted_rows == 5
    assert project.analyze(original_snapshot_id).tables == original_analysis.tables


@pytest.mark.parametrize("failed_step", ["workbook", "charts", "slides"])
@pytest.mark.parametrize("failure_timing", ["before", "after"])
def test_resume_recovers_before_and_after_each_publish_checkpoint(
    tmp_path, failed_step: str, failure_timing: str
) -> None:
    project, _, _ = _project(tmp_path)

    class FaultPublisher(FakeReportPublisher):
        armed = True

        def publish_step(self, step, content, plan):
            if step == failed_step and self.armed and failure_timing == "before":
                self.armed = False
                raise PublishingError("injected failure before checkpoint")
            super().publish_step(step, content, plan)
            if step == failed_step and self.armed and failure_timing == "after":
                self.armed = False
                raise PublishingError("injected failure after checkpoint")

    publisher = FaultPublisher()
    project.publisher = publisher
    with pytest.raises(PublishingError, match="injected failure"):
        project.refresh()

    run_id = next((tmp_path / "runtime" / "runs").glob("*.json")).stem
    failed = project.inspect_run(run_id)
    assert failed.status == RunStatus.FAILED
    assert failed.analysis is not None
    saved_analysis = failed.analysis
    saved_snapshot_id = failed.snapshot_id

    class MustNotReadSource:
        def read(self, source):
            raise AssertionError("resume tried to acquire a new source snapshot")

    project.source = MustNotReadSource()
    project._runner.source = project.source
    recovered = project.resume(run_id)
    manifest = project._runs.load(run_id)

    assert recovered.status == RunStatus.COMPLETED
    assert recovered.snapshot_id == saved_snapshot_id
    assert recovered.analysis == saved_analysis
    assert manifest.completed_steps[-4:] == ("workbook", "charts", "slides", "publish")
    assert len(publisher.workbook_objects) == 7
    assert len(publisher.objects) == 17
    assert len({entry.object_id for entry in publisher.mapping.entries}) == 17
