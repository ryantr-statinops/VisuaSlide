"""Opt-in live checks. Set VISUASLIDE_SANDBOX_CONFIG to a local sandbox TOML."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from googleapiclient.discovery import build

from visuaslide import SurveyProject
from visuaslide.exceptions import PublishingError
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.google_outputs import MIME_TYPES, ManagedOutputRegistry
from visuaslide.google_publisher import GoogleReportPublisher, managed_sheet_identity
from visuaslide.google_source import GoogleSheetSource
from visuaslide.models import AnalysisResult, RunStatus, Scalar
from visuaslide.reporting import build_presentation_content
from visuaslide.storage import SnapshotStore

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


def _read_report(
    publisher: GoogleReportPublisher,
) -> tuple[ManagedOutputRegistry, list[dict[str, Any]], list[dict[str, Any]]]:
    registry = publisher.store.load_or_create()
    files = publisher.drive.files()
    request = files.list(
        q=(
            "trashed = false and appProperties has "
            f"{{ key='visuaslide_project' and value='{registry.project_id}' }}"
        ),
        fields="nextPageToken,files(id,mimeType,appProperties)",
    )
    found = []
    while request is not None:
        response = request.execute()
        found.extend(
            (file["appProperties"]["visuaslide_role"], file["id"], file["mimeType"])
            for file in response.get("files", [])
        )
        request = files.list_next(request, response)
    assert set(registry.files) == set(MIME_TYPES)
    assert sorted(found) == sorted(
        (role, file_id, MIME_TYPES[role]) for role, file_id in registry.files.items()
    )
    assert len(set(registry.files.values())) == len(MIME_TYPES)
    assert publisher.config.source.spreadsheet_id not in registry.files.values()

    workbook = (
        publisher.sheets.spreadsheets()
        .get(spreadsheetId=registry.files["workbook"], fields="sheets(properties,charts(chartId))")
        .execute()
    )
    deck = (
        publisher.slides.presentations()
        .get(
            presentationId=registry.files["presentation"],
            fields="slides(objectId,pageElements(objectId,sheetsChart(spreadsheetId,chartId),"
            "shape(text),table(tableRows)))",
        )
        .execute()
    )
    return registry, workbook["sheets"], deck["slides"]


def _report_identities(
    registry: ManagedOutputRegistry, tabs: list[dict[str, Any]], slides: list[dict[str, Any]]
) -> tuple:
    tabs_by_id = {tab["properties"]["sheetId"]: tab for tab in tabs}
    elements = {
        item["objectId"]: item for slide in slides for item in slide.get("pageElements", [])
    }
    chart_ids = []
    linked_ids = []
    for entry in registry.mapping.entries:
        assert entry.object_id in elements
        if entry.kind not in {"table", "chart"}:
            continue
        analysis_id = entry.object_key.split(":", 1)[1]
        sheet_id, title = managed_sheet_identity(registry.project_id, analysis_id)
        tab = tabs_by_id[sheet_id]
        assert tab["properties"]["title"] == title
        if entry.kind == "chart":
            (chart,) = tab.get("charts", [])
            chart_ids.append(chart["chartId"])
            link = elements[entry.object_id]["sheetsChart"]
            assert link["spreadsheetId"] == registry.files["workbook"]
            assert link["chartId"] == chart["chartId"]
            linked_ids.append(entry.object_id)

    assert sorted(chart_ids) == sorted(
        chart["chartId"] for tab in tabs for chart in tab.get("charts", [])
    )
    assert sorted(linked_ids) == sorted(
        item["objectId"]
        for slide in slides
        for item in slide.get("pageElements", [])
        if "sheetsChart" in item
    )
    return (
        registry.files,
        sorted(
            (tab["properties"]["sheetId"], sorted(c["chartId"] for c in tab.get("charts", [])))
            for tab in tabs
        ),
        [
            (slide["objectId"], sorted(item["objectId"] for item in slide.get("pageElements", [])))
            for slide in slides
        ],
    )


def _workbook_row(row: Sequence[Scalar]) -> tuple[Scalar, ...]:
    values = [None if value == "" else value for value in row]
    while values and values[-1] is None:
        values.pop()
    return tuple(values)


def _slide_text(container: dict[str, Any]) -> str:
    return "".join(
        element.get("textRun", {}).get("content", "")
        for element in container.get("text", {}).get("textElements", [])
    ).removesuffix("\n")


def _assert_published_content(
    publisher: GoogleReportPublisher,
    registry: ManagedOutputRegistry,
    slides: list[dict[str, Any]],
    analysis: AnalysisResult,
) -> None:
    content = build_presentation_content(analysis, publisher.config.report)
    by_key = {entry.object_key: entry.object_id for entry in registry.mapping.entries}
    elements = {
        item["objectId"]: item for slide in slides for item in slide.get("pageElements", [])
    }
    assert _slide_text(elements[by_key["title:report"]]["shape"]) == content.title
    for block in content.text_blocks:
        shape = elements[by_key[f"text:{block.object_id}"]]["shape"]
        assert _slide_text(shape) == block.text

    expected_ranges: dict[str, list[tuple[Scalar, ...]]] = {}
    for table in content.tables:
        _, title = managed_sheet_identity(registry.project_id, table.source_analysis_id)
        rows = [table.columns, *table.rows]
        expected_ranges[f"'{title}'!A:I"] = rows
        element = elements[by_key[f"table:{table.source_analysis_id}"]]
        actual_rows = [
            [_slide_text(cell) for cell in row["tableCells"]]
            for row in element["table"]["tableRows"]
        ]
        assert actual_rows == [["—" if cell is None else str(cell) for cell in row] for row in rows]

    for chart in content.charts:
        _, title = managed_sheet_identity(registry.project_id, chart.source_analysis_id)
        link = elements[by_key[f"chart:{chart.source_analysis_id}"]]["sheetsChart"]
        assert link["spreadsheetId"] == registry.files["workbook"]
        expected_ranges[f"'{title}'!J:P"] = [
            ("category", *(series.label for series in chart.series)),
            *(
                (category, *(series.values[index] for series in chart.series))
                for index, category in enumerate(chart.categories)
            ),
        ]

    result = (
        publisher.sheets.spreadsheets()
        .values()
        .batchGet(
            spreadsheetId=registry.files["workbook"],
            ranges=list(expected_ranges),
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    for value_range, (a1_range, rows) in zip(
        result["valueRanges"], expected_ranges.items(), strict=True
    ):
        expected = [
            tuple(
                pytest.approx(value, rel=1e-12, abs=1e-12) if isinstance(value, float) else value
                for value in _workbook_row(row)
            )
            for row in rows
        ]
        assert [_workbook_row(row) for row in value_range.get("values", [])] == expected, a1_range


def test_sandbox_bootstrap_refresh_repeat_and_source_read_only() -> None:
    project = _project()
    before = _source_values(project)
    first_outputs = project.bootstrap_outputs()
    publisher = GoogleReportPublisher.from_config(project.config)
    first = project.refresh()
    first_report = _read_report(publisher)
    assert first.status == RunStatus.COMPLETED
    assert first.analysis is not None
    _assert_published_content(publisher, first_report[0], first_report[2], first.analysis)

    second_outputs = project.bootstrap_outputs()
    second = project.refresh()
    second_report = _read_report(publisher)

    assert first_outputs == second_outputs == first_report[0].files
    assert second.status == RunStatus.COMPLETED
    assert second.analysis is not None
    assert first.analysis.tables == second.analysis.tables
    assert _report_identities(*first_report) == _report_identities(*second_report)
    _assert_published_content(publisher, second_report[0], second_report[2], second.analysis)
    assert _source_values(project) == before

    store = SnapshotStore(project.config.project_dir)
    for result in (first, second):
        assert result.snapshot_id is not None
        captured = store.load(result.snapshot_id).snapshot
        assert (captured.headers, captured.rows) == before

    expected_rows = os.getenv("VISUASLIDE_SANDBOX_EXPECTED_ROWS")
    if expected_rows:
        assert second.analysis.accepted_rows == int(expected_rows)
    prior_snapshot = os.getenv("VISUASLIDE_SANDBOX_PRIOR_SNAPSHOT")
    if prior_snapshot:
        prior = store.load(prior_snapshot).snapshot
        assert (prior.headers, prior.rows) != before, "The scenario did not change source values."


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
