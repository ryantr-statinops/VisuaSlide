from pathlib import Path
from unittest.mock import Mock

import pytest

from visuaslide.config import load_config
from visuaslide.exceptions import PublishingError
from visuaslide.google_outputs import ManagedOutputStore
from visuaslide.google_publisher import GoogleReportPublisher, managed_sheet_identity
from visuaslide.reporting import ReportTable

ROOT = Path(__file__).parents[2]


def _publisher(tmp_path):
    config = load_config(ROOT / "examples/survey.example.toml").model_copy(
        update={"project_dir": tmp_path}
    )
    store = ManagedOutputStore(tmp_path)
    registry = store.load_or_create()
    store.save(registry.model_copy(update={"files": {"workbook": "workbook-id"}}))
    sheets, drive = Mock(), Mock()
    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "workbook-id",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "appProperties": {
            "visuaslide_project": registry.project_id,
            "visuaslide_role": "workbook",
        },
    }
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {"sheets": []}
    return GoogleReportPublisher(config, sheets, drive, Mock()), sheets, registry


def test_workbook_tables_clear_old_rows_and_write_only_managed_tab(tmp_path) -> None:
    publisher, sheets, registry = _publisher(tmp_path)
    table = ReportTable(
        object_id="table_answers",
        title="Answers",
        columns=("category", "frequency"),
        rows=(("Yes", 3), ("No", 1)),
        source_analysis_id="answers",
    )
    publisher._write_tables((table,))
    sheet_id, title = managed_sheet_identity(registry.project_id, "answers")
    sheet_requests = sheets.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]
    assert sheet_requests == {
        "requests": [{"addSheet": {"properties": {"sheetId": sheet_id, "title": title}}}]
    }
    clear_call = sheets.spreadsheets.return_value.values.return_value.clear.call_args.kwargs
    update_call = sheets.spreadsheets.return_value.values.return_value.update.call_args.kwargs
    assert clear_call["spreadsheetId"] == update_call["spreadsheetId"] == "workbook-id"
    assert clear_call["range"] == f"'{title}'"
    assert update_call["body"]["values"] == [
        ["category", "frequency"],
        ["Yes", 3],
        ["No", 1],
    ]


def test_workbook_write_rejects_sheet_id_collision_before_value_changes(tmp_path) -> None:
    publisher, sheets, registry = _publisher(tmp_path)
    sheet_id, _ = managed_sheet_identity(registry.project_id, "answers")
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"sheetId": sheet_id, "title": "User data"}}]
    }
    table = ReportTable(
        object_id="table_answers",
        title="Answers",
        columns=("category", "frequency"),
        rows=(("Yes", 3),),
        source_analysis_id="answers",
    )
    with pytest.raises(PublishingError, match="collides"):
        publisher._write_tables((table,))
    sheets.spreadsheets.return_value.values.assert_not_called()
