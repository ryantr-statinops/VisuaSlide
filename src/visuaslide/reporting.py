"""Presentation content derived from the canonical analysis result."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from visuaslide.config import ReportConfig, StrictModel
from visuaslide.models import AnalysisResult, AnalysisTable, Scalar

CATEGORIES_PER_PAGE = 10
type LayoutVersion = Literal["1", "2"]


def report_page_keys(analysis_id: str, category_count: int) -> tuple[str, ...]:
    """Retain the first page key and keep continuation keys outside analysis-ID syntax."""
    return tuple(
        analysis_id if offset == 0 else f"{analysis_id}/page/{offset // CATEGORIES_PER_PAGE + 1}"
        for offset in range(0, max(category_count, 1), CATEGORIES_PER_PAGE)
    )


def projection_object_id(kind: str, analysis_id: str, page_key: str | None) -> str:
    if page_key is None:
        return f"{kind}_{analysis_id}"
    return f"{kind}__page_{hashlib.sha256(page_key.encode()).hexdigest()[:24]}"


class ReportText(StrictModel):
    """One authored or mechanically rendered text block."""

    object_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str
    source_analysis_id: str | None = None
    page_key: str | None = None


class ReportTable(StrictModel):
    """Tabular content copied from one analysis result table."""

    object_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    source_analysis_id: str
    page_key: str | None = None

    @property
    def publication_key(self) -> str:
        return self.page_key or self.source_analysis_id


class ChartSeries(StrictModel):
    """One chart series with values kept in category order."""

    label: str
    values: tuple[int | float | None, ...]


class ReportChart(StrictModel):
    """A chart projection of an analysis table, without recalculation."""

    object_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    chart_type: Literal["bar", "column"] = "column"
    categories: tuple[str, ...]
    series: tuple[ChartSeries, ...]
    source_analysis_id: str
    page_key: str | None = None

    @property
    def publication_key(self) -> str:
        return self.page_key or self.source_analysis_id


class PresentationContent(StrictModel):
    """Content model consumed by offline and Google reporting adapters."""

    run_id: str
    snapshot_id: str
    title: str
    locale: str
    text_blocks: tuple[ReportText, ...]
    tables: tuple[ReportTable, ...]
    charts: tuple[ReportChart, ...]
    layout_version: LayoutVersion = "1"


def build_presentation_content(
    analysis: AnalysisResult, report: ReportConfig, *, layout_version: LayoutVersion = "2"
) -> PresentationContent:
    """Build text, tables, and chart projections from one AnalysisResult."""
    texts = [ReportText(object_id="sample_size", text=f"Valid responses: {analysis.accepted_rows}")]
    authored_fields = (
        ("research_question", report.research_question),
        ("sampling_method", report.sampling_method),
        ("collection_period", report.collection_period),
        ("conclusion", report.conclusion),
    )
    texts.extend(
        ReportText(object_id=object_id, text=value) for object_id, value in authored_fields if value
    )

    tables = []
    charts = []
    for table in analysis.tables:
        keys = (
            report_page_keys(table.analysis_id, len(table.rows))
            if layout_version == "2" and {"category", "frequency"}.issubset(table.columns)
            else (table.analysis_id,)
        )
        for index, key in enumerate(keys):
            page_key = key if index else None
            page = table
            if len(keys) > 1:
                start = index * CATEGORIES_PER_PAGE
                page = table.model_copy(
                    update={"rows": table.rows[start : start + CATEGORIES_PER_PAGE]}
                )
            projection = _table_projection(page, page_key)
            if len(keys) > 1:
                projection = projection.model_copy(
                    update={"title": f"{projection.title} ({index + 1}/{len(keys)})"}
                )
            tables.append(projection)
            chart = _chart_projection(page, page_key)
            if chart is not None:
                charts.append(chart.model_copy(update={"title": projection.title}))
            texts.append(_table_caption(page, page_key))

    return PresentationContent(
        run_id=analysis.run_id,
        snapshot_id=analysis.snapshot_id,
        title=report.title,
        locale=report.locale,
        text_blocks=tuple(texts),
        tables=tuple(tables),
        charts=tuple(charts),
        layout_version=layout_version,
    )


def _table_projection(table: AnalysisTable, page_key: str | None = None) -> ReportTable:
    return ReportTable(
        object_id=projection_object_id("table", table.analysis_id, page_key),
        title=_humanize(table.analysis_id),
        columns=table.columns,
        rows=table.rows,
        source_analysis_id=table.analysis_id,
        page_key=page_key,
    )


def _chart_projection(table: AnalysisTable, page_key: str | None = None) -> ReportChart | None:
    if "category" in table.columns and "frequency" in table.columns:
        category_index = table.columns.index("category")
        value_index = table.columns.index("frequency")
        categories = tuple(str(row[category_index]) for row in table.rows)
        series = (
            ChartSeries(
                label="Frequency",
                values=tuple(_numeric_or_none(row[value_index]) for row in table.rows),
            ),
        )
    elif {"row_category", "column_category", "frequency"}.issubset(table.columns):
        row_index = table.columns.index("row_category")
        column_index = table.columns.index("column_category")
        value_index = table.columns.index("frequency")
        categories = tuple(dict.fromkeys(str(row[row_index]) for row in table.rows))
        series_labels = tuple(dict.fromkeys(str(row[column_index]) for row in table.rows))
        lookup = {
            (str(row[row_index]), str(row[column_index])): _numeric_or_none(row[value_index])
            for row in table.rows
        }
        series = tuple(
            ChartSeries(
                label=label,
                values=tuple(lookup.get((category, label)) for category in categories),
            )
            for label in series_labels
        )
    else:
        return None
    return ReportChart(
        object_id=projection_object_id("chart", table.analysis_id, page_key),
        title=_humanize(table.analysis_id),
        categories=categories,
        series=series,
        source_analysis_id=table.analysis_id,
        page_key=page_key,
    )


def _table_caption(table: AnalysisTable, page_key: str | None = None) -> ReportText:
    rendered_rows = []
    for row in table.rows:
        rendered_rows.append(
            ", ".join(
                f"{column}: {_format_value(value)}"
                for column, value in zip(table.columns, row, strict=True)
            )
        )
    body = "; ".join(rendered_rows)
    return ReportText(
        object_id=projection_object_id("caption", table.analysis_id, page_key),
        text=f"{_humanize(table.analysis_id)} — {body}",
        source_analysis_id=table.analysis_id,
        page_key=page_key,
    )


def _numeric_or_none(value: Scalar) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _format_value(value: Scalar) -> str:
    if value is None:
        return "not available"
    return str(value)


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()
