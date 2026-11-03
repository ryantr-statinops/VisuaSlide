"""Run the complete synthetic survey workflow without network credentials."""

from __future__ import annotations

import json
from pathlib import Path

from visuaslide import SurveyProject
from visuaslide.publisher import FakeReportPublisher
from visuaslide.snapshots import SourceSnapshot, utc_now
from visuaslide.testing import FixtureSource

ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "examples" / "survey.example.toml"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "synthetic_responses.json"


def main() -> None:
    project_config = SurveyProject.from_toml(CONFIG_PATH).config
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    snapshot = SourceSnapshot.capture(
        project_config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(tuple(row) for row in fixture["rows"]),
        acquired_at=utc_now(),
    )
    project = SurveyProject(
        project_config,
        source=FixtureSource(snapshot),
        publisher=FakeReportPublisher(),
    )
    result = project.refresh()

    summary = {
        "run_id": result.run_id,
        "status": result.status.value,
        "stage": result.stage,
        "snapshot_id": result.snapshot_id,
        "input_rows": result.analysis.input_rows if result.analysis else None,
        "accepted_rows": result.analysis.accepted_rows if result.analysis else None,
        "analysis_tables": (
            [table.model_dump(mode="json") for table in result.analysis.tables]
            if result.analysis
            else []
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
