"""Managed aggregate workbook and Google Slides publication adapter."""

from __future__ import annotations

import hashlib
from typing import Any

from googleapiclient.discovery import build

from visuaslide.config import ProjectConfig
from visuaslide.exceptions import PublishingError
from visuaslide.google_auth import GoogleCredentialStore
from visuaslide.google_outputs import (
    ManagedOutputStore,
    verify_configured_output_ids,
    verify_managed_output,
)
from visuaslide.google_template import template_object_id
from visuaslide.layouts import build_default_layout
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
        registry = self.store.load_or_create()
        verify_configured_output_ids(config, registry)
        self._mapping = registry.mapping

    @classmethod
    def from_config(cls, config: ProjectConfig) -> GoogleReportPublisher:
        credentials = GoogleCredentialStore(config.project_dir).load()
        sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        slides = build("slides", "v1", credentials=credentials, cache_discovery=False)
        return cls(config, sheets, drive, slides)

    @property
    def mapping(self) -> ManagedObjectMap:
        return self._mapping

    def publish_step(self, step: str, content: PresentationContent, plan: ReportUpdatePlan) -> None:
        if step == "workbook":
            self._write_tables(content.tables)
            self._remove_obsolete_workbook_objects(plan)
            return
        if step == "charts":
            self._write_charts(content.charts)
            return
        if step == "slides":
            self._write_slide_text_tables(content, plan)
            self._write_slide_charts(content, plan)
            return
        raise PublishingError("Google reporting step is not implemented yet.")

    def _write_slide_text_tables(
        self, content: PresentationContent, plan: ReportUpdatePlan
    ) -> None:
        registry = self.store.load_or_create()
        deck_id = registry.files.get("presentation")
        if deck_id is None:
            raise PublishingError("Bootstrap the managed presentation before refresh.")
        verify_managed_output(
            self.drive,
            file_id=deck_id,
            role="presentation",
            project_id=registry.project_id,
            source_spreadsheet_id=self.config.source.spreadsheet_id,
        )
        try:
            deck = (
                self.slides.presentations()
                .get(
                    presentationId=deck_id,
                    fields="slides(objectId,pageElements(objectId,shape,table))",
                )
                .execute()
            )
        except Exception as exc:
            raise PublishingError("Could not inspect managed presentation elements.") from exc
        pages = {page["objectId"]: page for page in deck.get("slides", [])}
        elements = {
            item["objectId"]: item
            for page in pages.values()
            for item in page.get("pageElements", [])
        }
        layout = build_default_layout(content)
        text_pages = {
            text_id: template_object_id(f"slide:{slide.slide_key}")
            for slide in layout.slides
            for text_id in slide.text_ids
        }
        table_pages = {
            table_id: template_object_id(f"slide:{slide.slide_key}")
            for slide in layout.slides
            for table_id in slide.table_ids
        }
        prior_keys = {entry.object_key for entry in self._mapping.entries}
        requests: list[dict[str, object]] = []
        for operation in plan.operations:
            if operation.kind in {"title", "text"}:
                if operation.kind == "text":
                    page_id = text_pages.get(operation.object_key.removeprefix("text:"))
                    if page_id not in pages:
                        raise PublishingError("A required managed text slide is missing.")
                if operation.object_id not in elements:
                    raise PublishingError("A required managed text element is missing from Slides.")
                text = operation.payload["text"]
                requests.extend(
                    [
                        {
                            "deleteText": {
                                "objectId": operation.object_id,
                                "textRange": {"type": "ALL"},
                            }
                        },
                        {"insertText": {"objectId": operation.object_id, "text": str(text)}},
                    ]
                )
            elif operation.kind == "table":
                table_id = operation.object_id
                table_content = next(
                    item
                    for item in content.tables
                    if item.source_analysis_id == operation.object_key.removeprefix("table:")
                )
                if table_id not in elements and operation.object_key in prior_keys:
                    raise PublishingError("A mapped managed table is missing from Slides.")
                page_id = table_pages[table_content.object_id]
                if page_id not in pages:
                    raise PublishingError("A required managed analysis slide is missing.")
                if table_id in elements:
                    requests.append({"deleteObject": {"objectId": table_id}})
                requests.append(
                    {
                        "createTable": {
                            "objectId": table_id,
                            "rows": len(table_content.rows) + 1,
                            "columns": len(table_content.columns),
                            "elementProperties": {
                                "pageObjectId": page_id,
                                "size": {
                                    "width": {"magnitude": 300, "unit": "PT"},
                                    "height": {"magnitude": 200, "unit": "PT"},
                                },
                                "transform": {
                                    "scaleX": 1,
                                    "scaleY": 1,
                                    "translateX": 40,
                                    "translateY": 170,
                                    "unit": "PT",
                                },
                            },
                        }
                    }
                )
                for row_index, row in enumerate((table_content.columns, *table_content.rows)):
                    for column_index, value in enumerate(row):
                        requests.append(
                            {
                                "insertText": {
                                    "objectId": table_id,
                                    "cellLocation": {
                                        "rowIndex": row_index,
                                        "columnIndex": column_index,
                                    },
                                    "text": "—" if value is None else str(value),
                                }
                            }
                        )
        if requests:
            try:
                self.slides.presentations().batchUpdate(
                    presentationId=deck_id, body={"requests": requests}
                ).execute()
            except Exception as exc:
                raise PublishingError("Could not update managed slide text and tables.") from exc
        non_chart_entries = tuple(entry for entry in plan.mapping.entries if entry.kind != "chart")
        prior_chart_entries = tuple(
            entry for entry in self._mapping.entries if entry.kind == "chart"
        )
        self._mapping = ManagedObjectMap(entries=non_chart_entries + prior_chart_entries)
        self.store.save(registry.model_copy(update={"mapping": self._mapping}))

    def _write_slide_charts(self, content: PresentationContent, plan: ReportUpdatePlan) -> None:
        if not content.charts:
            return
        registry = self.store.load_or_create()
        workbook_id = registry.files.get("workbook")
        deck_id = registry.files.get("presentation")
        if workbook_id is None or deck_id is None:
            raise PublishingError("Bootstrap managed Google outputs before chart publication.")
        for role, file_id in (("workbook", workbook_id), ("presentation", deck_id)):
            verify_managed_output(
                self.drive,
                file_id=file_id,
                role=role,
                project_id=registry.project_id,
                source_spreadsheet_id=self.config.source.spreadsheet_id,
            )
        try:
            workbook = (
                self.sheets.spreadsheets()
                .get(
                    spreadsheetId=workbook_id,
                    fields="sheets(properties(sheetId,title),charts(chartId))",
                )
                .execute()
            )
            deck = (
                self.slides.presentations()
                .get(
                    presentationId=deck_id,
                    fields="slides(objectId,pageElements(objectId,sheetsChart))",
                )
                .execute()
            )
        except Exception as exc:
            raise PublishingError("Could not inspect managed linked charts.") from exc
        source_sheets = {
            sheet["properties"]["sheetId"]: sheet for sheet in workbook.get("sheets", [])
        }
        pages = {page["objectId"]: page for page in deck.get("slides", [])}
        objects = {
            item["objectId"]: item
            for page in pages.values()
            for item in page.get("pageElements", [])
        }
        prior_keys = {entry.object_key for entry in self._mapping.entries if entry.kind == "chart"}
        requests: list[dict[str, object]] = []
        for chart in content.charts:
            key = f"chart:{chart.source_analysis_id}"
            operation = next(item for item in plan.operations if item.object_key == key)
            sheet_id, title = managed_sheet_identity(registry.project_id, chart.source_analysis_id)
            source_sheet = source_sheets.get(sheet_id)
            if source_sheet is None or source_sheet["properties"]["title"] != title:
                raise PublishingError("A linked source chart tab is missing or changed.")
            chart_ids = [item["chartId"] for item in source_sheet.get("charts", [])]
            if len(chart_ids) != 1:
                raise PublishingError("A linked source chart is missing or ambiguous.")
            page_id = template_object_id(f"slide:analysis_{chart.source_analysis_id}")
            if page_id not in pages:
                raise PublishingError("A required managed chart slide is missing.")
            if operation.object_id in objects:
                requests.append({"refreshSheetsChart": {"objectId": operation.object_id}})
            elif key in prior_keys:
                raise PublishingError("A mapped linked chart is missing from Slides.")
            else:
                requests.append(
                    {
                        "createSheetsChart": {
                            "objectId": operation.object_id,
                            "spreadsheetId": workbook_id,
                            "chartId": chart_ids[0],
                            "linkingMode": "LINKED",
                            "elementProperties": {
                                "pageObjectId": page_id,
                                "size": {
                                    "width": {"magnitude": 300, "unit": "PT"},
                                    "height": {"magnitude": 220, "unit": "PT"},
                                },
                                "transform": {
                                    "scaleX": 1,
                                    "scaleY": 1,
                                    "translateX": 380,
                                    "translateY": 170,
                                    "unit": "PT",
                                },
                            },
                        }
                    }
                )
        if requests:
            try:
                self.slides.presentations().batchUpdate(
                    presentationId=deck_id, body={"requests": requests}
                ).execute()
            except Exception as exc:
                raise PublishingError("Could not embed or refresh managed linked charts.") from exc
        self._mapping = plan.mapping
        self.store.save(registry.model_copy(update={"mapping": self._mapping}))

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
            sheet_id, title = managed_sheet_identity(registry.project_id, table.publication_key)
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
            sheet_id, title = managed_sheet_identity(registry.project_id, chart.publication_key)
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

    def _remove_obsolete_workbook_objects(self, plan: ReportUpdatePlan) -> None:
        removed = [entry for entry in plan.removed if entry.kind in {"table", "chart"}]
        if not removed:
            return
        registry = self.store.load_or_create()
        workbook_id = registry.files["workbook"]
        verify_managed_output(
            self.drive,
            file_id=workbook_id,
            role="workbook",
            project_id=registry.project_id,
            source_spreadsheet_id=self.config.source.spreadsheet_id,
        )
        try:
            workbook = (
                self.sheets.spreadsheets()
                .get(spreadsheetId=workbook_id, fields="sheets(properties,charts(chartId))")
                .execute()
            )
            tabs = {tab["properties"]["sheetId"]: tab for tab in workbook.get("sheets", [])}
            removed_tables = {
                entry.object_key.removeprefix("table:")
                for entry in removed
                if entry.kind == "table"
            }
            requests = []
            for key in dict.fromkeys(entry.object_key.split(":", 1)[1] for entry in removed):
                sheet_id, title = managed_sheet_identity(registry.project_id, key)
                tab = tabs.get(sheet_id)
                if tab is None:
                    continue
                if tab["properties"]["title"] != title:
                    raise PublishingError("An obsolete managed reporting tab was renamed.")
                if key in removed_tables:
                    requests.append({"deleteSheet": {"sheetId": sheet_id}})
                else:
                    charts = tab.get("charts", [])
                    if len(charts) > 1:
                        raise PublishingError("An obsolete managed chart is ambiguous.")
                    requests.extend(
                        {"deleteEmbeddedObject": {"objectId": chart["chartId"]}} for chart in charts
                    )
                    self.sheets.spreadsheets().values().clear(
                        spreadsheetId=workbook_id, range=f"'{title}'!J:P", body={}
                    ).execute()
            if requests:
                self.sheets.spreadsheets().batchUpdate(
                    spreadsheetId=workbook_id, body={"requests": requests}
                ).execute()
        except PublishingError:
            raise
        except Exception as exc:
            raise PublishingError("Could not remove obsolete managed workbook objects.") from exc

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
