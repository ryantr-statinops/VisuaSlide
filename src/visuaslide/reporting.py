"""Presentation content derived from the canonical analysis result."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from visuaslide.config import ReportConfig, StrictModel
from visuaslide.models import AnalysisResult, AnalysisTable, Scalar


class ReportText(StrictModel):
    """One authored or mechanically rendered text block."""

    object_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    text: str
    source_analysis_id: str | None = None


class ReportTable(StrictModel):
    """Tabular content copied from one analysis result table."""

    object_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    source_analysis_id: str


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


class PresentationContent(StrictModel):
    """Content model consumed by offline and Google reporting adapters."""

    run_id: str
    snapshot_id: str
    title: str
    locale: str
    text_blocks: tuple[ReportText, ...]
    tables: tuple[ReportTable, ...]
    charts: tuple[ReportChart, ...]


def build_presentation_content(
    analysis: AnalysisResult, report: ReportConfig
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

    tables = tuple(_table_projection(table) for table in analysis.tables)
    charts = tuple(
        chart for table in analysis.tables if (chart := _chart_projection(table)) is not None
    )
    texts.extend(_table_caption(table) for table in analysis.tables)

    return PresentationContent(
        run_id=analysis.run_id,
        snapshot_id=analysis.snapshot_id,
        title=report.title,
        locale=report.locale,
        text_blocks=tuple(texts),
        tables=tables,
        charts=charts,
    )


def _table_projection(table: AnalysisTable) -> ReportTable:
    return ReportTable(
        object_id=f"table_{table.analysis_id}",
        title=_humanize(table.analysis_id),
        columns=table.columns,
        rows=table.rows,
        source_analysis_id=table.analysis_id,
    )


def _chart_projection(table: AnalysisTable) -> ReportChart | None:
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
        object_id=f"chart_{table.analysis_id}",
        title=_humanize(table.analysis_id),
        categories=categories,
        series=series,
        source_analysis_id=table.analysis_id,
    )


def _table_caption(table: AnalysisTable) -> ReportText:
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
        object_id=f"caption_{table.analysis_id}",
        text=f"{_humanize(table.analysis_id)} — {body}",
        source_analysis_id=table.analysis_id,
    )


def _numeric_or_none(value: Scalar) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _format_value(value: Scalar) -> str:
    if value is None:
        return "not available"
    return str(value)


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()
