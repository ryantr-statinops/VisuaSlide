"""Read-only Google Sheets source adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from googleapiclient.discovery import build

from visuaslide.config import SourceConfig
from visuaslide.exceptions import ConfigurationError
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.snapshots import SourceSnapshot, utc_now


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

    def read(self, source: SourceConfig) -> SourceSnapshot:
        """Read the entire configured range without exposing a write operation."""
        tab = self.resolve_tab(source)
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=source.spreadsheet_id,
                    range=tab.data_range(source),
                    majorDimension="ROWS",
                    valueRenderOption="UNFORMATTED_VALUE",
                    dateTimeRenderOption="FORMATTED_STRING",
                )
                .execute()
            )
        except Exception as exc:
            raise ConfigurationError("Could not read the configured Google Sheets range.") from exc
        rows = response.get("values", [])
        return SourceSnapshot.capture(
            source,
            headers=tuple(str(value) for value in rows[0]) if rows else (),
            rows=tuple(tuple(row) for row in rows[1:]),
            acquired_at=utc_now(),
            value_render_option="UNFORMATTED_VALUE",
            date_time_render_option="FORMATTED_STRING",
            locale=tab.locale,
            timezone=tab.timezone,
        )


class LazyGoogleSheetSource:
    """Delay credential loading until a fresh source read is requested."""

    def __init__(self, project_dir) -> None:
        self._credential_store = GoogleCredentialStore(project_dir)

    def read(self, source: SourceConfig) -> SourceSnapshot:
        credentials = self._credential_store.load()
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return GoogleSheetSource(service).read(source)
