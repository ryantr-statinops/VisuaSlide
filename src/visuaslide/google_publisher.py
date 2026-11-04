"""Managed aggregate workbook and Google Slides publication adapter."""

from __future__ import annotations

import hashlib
from typing import Any

from visuaslide.config import ProjectConfig
from visuaslide.exceptions import PublishingError
from visuaslide.google_outputs import ManagedOutputStore, verify_managed_output
from visuaslide.reporting import PresentationContent, ReportTable
from visuaslide.update_plan import ManagedObjectMap, ReportUpdatePlan


def managed_sheet_identity(project_id: str, analysis_id: str) -> tuple[int, str]:
    """Deterministic numeric sheet ID and title for one managed analysis table."""
    digest = hashlib.sha256(f"{project_id}:{analysis_id}".encode()).hexdigest()
    return int(digest[:7], 16) + 1, f"vs_{digest[:16]}"


class GoogleReportPublisher:
    def __init__(self, config: ProjectConfig, sheets: Any, drive: Any, slides: Any) -> None:
        self.config = config
        self.sheets = sheets
        self.drive = drive
        self.slides = slides
        self.store = ManagedOutputStore(config.project_dir)
        self._mapping = ManagedObjectMap()

    @property
    def mapping(self) -> ManagedObjectMap:
        return self._mapping

    def publish_step(self, step: str, content: PresentationContent, plan: ReportUpdatePlan) -> None:
        if step == "workbook":
            self._write_tables(content.tables)
            return
        raise PublishingError("Google reporting step is not implemented yet.")

    def _write_tables(self, tables: tuple[ReportTable, ...]) -> None:
        registry = self.store.load_or_create()
        workbook_id = registry.files.get("workbook")
        if workbook_id is None:
            raise PublishingError("Bootstrap the managed reporting workbook before refresh.")
        verify_managed_output(
            self.drive,
            file_id=workbook_id,
            role="workbook",
            project_id=registry.project_id,
            source_spreadsheet_id=self.config.source.spreadsheet_id,
        )
        try:
            metadata = (
                self.sheets.spreadsheets()
                .get(spreadsheetId=workbook_id, fields="sheets(properties(sheetId,title))")
                .execute()
            )
        except Exception as exc:
            raise PublishingError("Could not inspect managed reporting sheets.") from exc
        existing = {
            sheet["properties"]["sheetId"]: sheet["properties"]["title"]
            for sheet in metadata.get("sheets", [])
        }
        for table in tables:
            sheet_id, title = managed_sheet_identity(registry.project_id, table.source_analysis_id)
            if sheet_id in existing and existing[sheet_id] != title:
                raise PublishingError("A managed sheet ID collides with another workbook tab.")
            if sheet_id not in existing:
                try:
                    request = {"addSheet": {"properties": {"sheetId": sheet_id, "title": title}}}
                    self.sheets.spreadsheets().batchUpdate(
                        spreadsheetId=workbook_id,
                        body={"requests": [request]},
                    ).execute()
                except Exception as exc:
                    raise PublishingError("Could not create a managed reporting tab.") from exc
                existing[sheet_id] = title
            safe_title = title.replace("'", "''")
            tab_range = f"'{safe_title}'"
            values = [list(table.columns), *(list(row) for row in table.rows)]
            try:
                self.sheets.spreadsheets().values().clear(
                    spreadsheetId=workbook_id, range=tab_range, body={}
                ).execute()
                self.sheets.spreadsheets().values().update(
                    spreadsheetId=workbook_id,
                    range=f"{tab_range}!A1",
                    valueInputOption="RAW",
                    body={"values": values},
                ).execute()
            except Exception as exc:
                raise PublishingError("Could not update managed aggregate values.") from exc
