"""Fixed widescreen report layout and overflow checks."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from visuaslide.config import StrictModel
from visuaslide.exceptions import PublishingError
from visuaslide.reporting import PresentationContent


class SlideLayout(StrictModel):
    """One fixed role-based slide and the managed content placed on it."""

    slide_key: str
    role: Literal["cover", "context", "conclusion", "analysis"]
    title: str
    text_ids: tuple[str, ...] = ()
    table_ids: tuple[str, ...] = ()
    chart_ids: tuple[str, ...] = ()


class PresentationLayout(StrictModel):
    """Default 16:9 presentation layout specification."""

    width_inches: float = Field(default=13.333333, gt=0)
    height_inches: float = Field(default=7.5, gt=0)
    locale: str = "vi-VN"
    slides: tuple[SlideLayout, ...] = Field(min_length=1)


class LayoutLimits(StrictModel):
    """Conservative content bounds for the fixed default layout."""

    max_title_characters: int = Field(default=72, ge=1)
    max_text_characters: int = Field(default=2400, ge=1)
    max_table_rows: int = Field(default=18, ge=1)
    max_table_columns: int = Field(default=8, ge=1)
    max_cell_characters: int = Field(default=120, ge=1)
    max_chart_categories: int = Field(default=10, ge=1)
    max_chart_series: int = Field(default=6, ge=1)
    max_chart_label_characters: int = Field(default=64, ge=1)


def build_default_layout(
    content: PresentationContent,
    limits: LayoutLimits | None = None,
) -> PresentationLayout:
    """Validate all content bounds and create role-based 16:9 slide layouts."""
    limits = limits or LayoutLimits()
    overflows = _find_overflows(content, limits)
    if overflows:
        raise PublishingError("Report content exceeds the default layout: " + "; ".join(overflows))

    text_by_id = {item.object_id: item for item in content.text_blocks}
    context_ids = tuple(
        object_id
        for object_id in (
            "research_question",
            "sampling_method",
            "collection_period",
            "sample_size",
        )
        if object_id in text_by_id
    )
    conclusion_ids = ("conclusion",) if "conclusion" in text_by_id else ()
    slides = [
        SlideLayout(
            slide_key="cover",
            role="cover",
            title=content.title,
            text_ids=tuple(item for item in context_ids if item == "research_question"),
        )
    ]
    if any(object_id != "research_question" for object_id in context_ids):
        slides.append(
            SlideLayout(
                slide_key="context",
                role="context",
                title="Phương pháp và mẫu",
                text_ids=tuple(item for item in context_ids if item != "research_question"),
            )
        )

    chart_ids_by_analysis = {item.source_analysis_id: item.object_id for item in content.charts}
    caption_ids_by_analysis = {
        item.source_analysis_id: item.object_id
        for item in content.text_blocks
        if item.object_id.startswith("caption_") and item.source_analysis_id
    }
    for table in content.tables:
        slides.append(
            SlideLayout(
                slide_key=f"analysis_{table.source_analysis_id}",
                role="analysis",
                title=table.title,
                text_ids=(caption_ids_by_analysis[table.source_analysis_id],)
                if table.source_analysis_id in caption_ids_by_analysis
                else (),
                table_ids=(table.object_id,),
                chart_ids=(chart_ids_by_analysis[table.source_analysis_id],)
                if table.source_analysis_id in chart_ids_by_analysis
                else (),
            )
        )
    if conclusion_ids:
        slides.append(
            SlideLayout(
                slide_key="conclusion",
                role="conclusion",
                title="Kết luận",
                text_ids=conclusion_ids,
            )
        )

    return PresentationLayout(locale=content.locale, slides=tuple(slides))


def _find_overflows(content: PresentationContent, limits: LayoutLimits) -> list[str]:
    issues = []
    if len(content.title) > limits.max_title_characters:
        issues.append(f"report title exceeds {limits.max_title_characters} characters")
    for text in content.text_blocks:
        if len(text.text) > limits.max_text_characters:
            issues.append(
                f"text object {text.object_id} exceeds {limits.max_text_characters} characters"
            )
    for table in content.tables:
        if len(table.rows) > limits.max_table_rows:
            issues.append(f"table {table.object_id} exceeds {limits.max_table_rows} rows")
        if len(table.columns) > limits.max_table_columns:
            issues.append(f"table {table.object_id} exceeds {limits.max_table_columns} columns")
        if any(
            isinstance(value, str) and len(value) > limits.max_cell_characters
            for row in table.rows
            for value in row
        ):
            issues.append(f"table {table.object_id} contains a cell label that is too long")
    for chart in content.charts:
        if len(chart.categories) > limits.max_chart_categories:
            issues.append(
                f"chart {chart.object_id} exceeds {limits.max_chart_categories} categories"
            )
        if len(chart.series) > limits.max_chart_series:
            issues.append(f"chart {chart.object_id} exceeds {limits.max_chart_series} series")
        if any(len(label) > limits.max_chart_label_characters for label in chart.categories):
            issues.append(f"chart {chart.object_id} contains an overlong category label")
        if any(len(series.label) > limits.max_chart_label_characters for series in chart.series):
            issues.append(f"chart {chart.object_id} contains an overlong series label")
    return issues
