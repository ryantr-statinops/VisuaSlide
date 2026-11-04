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
