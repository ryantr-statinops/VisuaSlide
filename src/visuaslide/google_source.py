"""Read-only Google Sheets source adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from visuaslide.config import SourceConfig
from visuaslide.exceptions import ConfigurationError


@dataclass(frozen=True)
class ResolvedSourceTab:
    title: str
    locale: str | None
    timezone: str | None

    def data_range(self, source: SourceConfig) -> str:
        first_column, last_column = source.column_range.split(":", maxsplit=1)
        safe_title = self.title.replace("'", "''")
        return f"'{safe_title}'!{first_column}{source.header_row}:{last_column}"


class GoogleSheetSource:
    """Resolve one configured sheet ID before constructing a values range."""

    def __init__(self, sheets_service: Any) -> None:
        self._service = sheets_service

    def resolve_tab(self, source: SourceConfig) -> ResolvedSourceTab:
        try:
            metadata = (
                self._service.spreadsheets()
                .get(
                    spreadsheetId=source.spreadsheet_id,
                    fields="properties(locale,timeZone),sheets(properties(sheetId,title))",
                    includeGridData=False,
                )
                .execute()
            )
        except Exception as exc:
            raise ConfigurationError("Could not read Google Sheets source metadata.") from exc
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("sheetId") == source.sheet_id:
                return ResolvedSourceTab(
                    title=properties["title"],
                    locale=metadata.get("properties", {}).get("locale"),
                    timezone=metadata.get("properties", {}).get("timeZone"),
                )
        raise ConfigurationError("The configured Google sheet ID does not exist in the source.")
