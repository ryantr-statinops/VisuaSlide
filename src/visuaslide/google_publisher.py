"""Managed aggregate workbook and Google Slides publication adapter."""

from __future__ import annotations

import hashlib
from typing import Any

from visuaslide.config import ProjectConfig
from visuaslide.exceptions import PublishingError
from visuaslide.google_outputs import ManagedOutputStore, verify_managed_output
from visuaslide.reporting import PresentationContent, ReportChart, ReportTable
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
        if step == "charts":
            self._write_charts(content.charts)
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

    def _write_charts(self, charts: tuple[ReportChart, ...]) -> None:
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
                .get(
                    spreadsheetId=workbook_id,
                    fields="sheets(properties(sheetId,title),charts(chartId,spec(title)))",
                )
                .execute()
            )
        except Exception as exc:
            raise PublishingError("Could not inspect managed Sheets charts.") from exc
        sheets = {sheet["properties"]["sheetId"]: sheet for sheet in metadata.get("sheets", [])}
        for chart in charts:
            sheet_id, title = managed_sheet_identity(registry.project_id, chart.source_analysis_id)
            sheet = sheets.get(sheet_id)
            if sheet is None or sheet["properties"]["title"] != title:
                raise PublishingError("A managed chart source tab is missing or changed.")
            existing_charts = sheet.get("charts", [])
            if len(existing_charts) > 1:
                raise PublishingError("Multiple charts exist on a managed reporting tab.")
            data = [["category", *(series.label for series in chart.series)]]
            data.extend(
                [category, *(series.values[index] for series in chart.series)]
                for index, category in enumerate(chart.categories)
            )
            safe_title = title.replace("'", "''")
            try:
                self.sheets.spreadsheets().values().clear(
                    spreadsheetId=workbook_id, range=f"'{safe_title}'!J:P", body={}
                ).execute()
                self.sheets.spreadsheets().values().update(
                    spreadsheetId=workbook_id,
                    range=f"'{safe_title}'!J1",
                    valueInputOption="RAW",
                    body={"values": data},
                ).execute()
            except Exception as exc:
                raise PublishingError("Could not update managed chart source values.") from exc
            spec = self._chart_spec(chart, sheet_id)
            if existing_charts:
                request = {
                    "updateChartSpec": {
                        "chartId": existing_charts[0]["chartId"],
                        "spec": spec,
                    }
                }
            else:
                request = {
                    "addChart": {
                        "chart": {
                            "spec": spec,
                            "position": {
                                "overlayPosition": {
                                    "anchorCell": {
                                        "sheetId": sheet_id,
                                        "rowIndex": 0,
                                        "columnIndex": 17,
                                    },
                                    "widthPixels": 720,
                                    "heightPixels": 420,
                                }
                            },
                        }
                    }
                }
            try:
                self.sheets.spreadsheets().batchUpdate(
                    spreadsheetId=workbook_id, body={"requests": [request]}
                ).execute()
            except Exception as exc:
                raise PublishingError("Could not create or update managed Sheets chart.") from exc

    @staticmethod
    def _chart_spec(chart: ReportChart, sheet_id: int) -> dict[str, object]:
        row_end = len(chart.categories) + 1

        def source_range(column: int) -> dict[str, object]:
            return {
                "sources": [
                    {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": row_end,
                        "startColumnIndex": column,
                        "endColumnIndex": column + 1,
                    }
                ]
            }

        palette = ((0.17, 0.39, 0.70), (0.89, 0.41, 0.20), (0.24, 0.62, 0.43))
        return {
            "title": chart.title,
            "basicChart": {
                "chartType": "BAR" if chart.chart_type == "bar" else "COLUMN",
                "legendPosition": "BOTTOM_LEGEND",
                "headerCount": 1,
                "domains": [{"domain": {"sourceRange": source_range(9)}}],
                "series": [
                    {
                        "series": {"sourceRange": source_range(10 + index)},
                        "targetAxis": "LEFT_AXIS",
                        "color": dict(
                            zip(
                                ("red", "green", "blue"),
                                palette[index % len(palette)],
                                strict=True,
                            )
                        ),
                    }
                    for index, _ in enumerate(chart.series)
                ],
            },
        }
