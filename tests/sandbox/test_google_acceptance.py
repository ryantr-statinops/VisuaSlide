"""Opt-in live checks. Set VISUASLIDE_SANDBOX_CONFIG to a local sandbox TOML."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from googleapiclient.discovery import build

from visuaslide import SurveyProject
from visuaslide.exceptions import PublishingError
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.google_publisher import GoogleReportPublisher
from visuaslide.google_source import GoogleSheetSource
from visuaslide.models import RunStatus

SANDBOX_CONFIG = os.getenv("VISUASLIDE_SANDBOX_CONFIG")
pytestmark = pytest.mark.skipif(not SANDBOX_CONFIG, reason="Google sandbox not configured")


def _project() -> SurveyProject:
    assert SANDBOX_CONFIG is not None
    return SurveyProject.from_toml(Path(SANDBOX_CONFIG))


def _source_values(project: SurveyProject):
    credentials = GoogleCredentialStore(project.config.project_dir).load()
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    snapshot = GoogleSheetSource(sheets).read(project.config.source)
    return snapshot.headers, snapshot.rows


def test_sandbox_bootstrap_refresh_repeat_and_source_read_only() -> None:
    project = _project()
    before = _source_values(project)
    first_outputs = project.bootstrap_outputs()
    first = project.refresh()
    second_outputs = project.bootstrap_outputs()
    second = project.refresh()

    assert first_outputs == second_outputs
    assert first.status == second.status == RunStatus.COMPLETED
    assert first.analysis is not None and second.analysis is not None
    assert first.analysis.tables == second.analysis.tables
    assert _source_values(project) == before

    expected_rows = os.getenv("VISUASLIDE_SANDBOX_EXPECTED_ROWS")
    if expected_rows:
        assert second.analysis.accepted_rows == int(expected_rows)
    prior_snapshot = os.getenv("VISUASLIDE_SANDBOX_PRIOR_SNAPSHOT")
    if prior_snapshot:
        assert second.snapshot_id != prior_snapshot


def test_sandbox_resume_after_workbook_side_effect_without_source_reacquisition() -> None:
    project = _project()
    project.bootstrap_outputs()
    before = _source_values(project)
    actual = GoogleReportPublisher.from_config(project.config)

    class FailAfterWorkbook:
        failed = False

        @property
        def mapping(self):
            return actual.mapping

        def publish_step(self, step, content, plan):
            actual.publish_step(step, content, plan)
            if step == "workbook" and not self.failed:
                self.failed = True
                raise PublishingError("sandbox checkpoint fault")

    project.publisher = FailAfterWorkbook()
    prior_runs = {path.stem for path in (project.config.project_dir / "runs").glob("*.json")}
    with pytest.raises(PublishingError, match="sandbox checkpoint fault"):
        project.refresh()
    new_runs = {path.stem for path in (project.config.project_dir / "runs").glob("*.json")}
    (run_id,) = new_runs - prior_runs
    failed = project.inspect_run(run_id)
    assert failed.status == RunStatus.FAILED
    assert failed.analysis is not None

    class MustNotRead:
        def read(self, source):
            raise AssertionError("resume read Google source")

    project.source = MustNotRead()
    project._runner.source = project.source
    recovered = project.resume(run_id)
    assert recovered.status == RunStatus.COMPLETED
    assert recovered.analysis == failed.analysis
    assert _source_values(project) == before
