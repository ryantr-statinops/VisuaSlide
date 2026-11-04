from unittest.mock import Mock

import pytest

from visuaslide.config import SourceConfig
from visuaslide.exceptions import ConfigurationError
from visuaslide.google_source import GoogleSheetSource


def _service(sheets):
    service = Mock()
    service.spreadsheets.return_value.get.return_value.execute.return_value = {
        "properties": {"locale": "vi_VN", "timeZone": "Asia/Ho_Chi_Minh"},
        "sheets": sheets,
    }
    return service


def test_tab_is_resolved_by_id_after_rename_and_title_is_escaped() -> None:
    service = _service([{"properties": {"sheetId": 7, "title": "Lớp 'A'"}}])
    source = SourceConfig(spreadsheet_id="source", sheet_id=7, column_range="B:D", header_row=3)

    tab = GoogleSheetSource(service).resolve_tab(source)

    assert tab.data_range(source) == "'Lớp ''A'''!B3:D"
    assert tab.locale == "vi_VN"
    assert tab.timezone == "Asia/Ho_Chi_Minh"
    service.spreadsheets.return_value.get.assert_called_once_with(
        spreadsheetId="source",
        fields="properties(locale,timeZone),sheets(properties(sheetId,title))",
        includeGridData=False,
    )


def test_missing_tab_id_stops_without_guessing_by_name() -> None:
    source = SourceConfig(spreadsheet_id="source", sheet_id=7, column_range="A:C")
    with pytest.raises(ConfigurationError, match="sheet ID does not exist"):
        GoogleSheetSource(
            _service([{"properties": {"sheetId": 8, "title": "Old name"}}])
        ).resolve_tab(source)


def test_google_read_captures_full_range_and_render_metadata() -> None:
    service = _service([{"properties": {"sheetId": 7, "title": "Khảo sát"}}])
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [
            ["Response ID", "Score", "Submitted at"],
            ["r1", 8, "2026-10-10 08:00"],
            ["r2", 9],
        ]
    }
    source = SourceConfig(spreadsheet_id="source", sheet_id=7, column_range="A:C")

    snapshot = GoogleSheetSource(service).read(source)

    assert snapshot.headers == ("Response ID", "Score", "Submitted at")
    assert snapshot.rows == (("r1", 8, "2026-10-10 08:00"), ("r2", 9))
    assert snapshot.metadata.value_render_option == "UNFORMATTED_VALUE"
    assert snapshot.metadata.date_time_render_option == "FORMATTED_STRING"
    assert snapshot.metadata.locale == "vi_VN"
    service.spreadsheets.return_value.values.return_value.get.assert_called_once_with(
        spreadsheetId="source",
        range="'Khảo sát'!A1:C",
        majorDimension="ROWS",
        valueRenderOption="UNFORMATTED_VALUE",
        dateTimeRenderOption="FORMATTED_STRING",
    )
