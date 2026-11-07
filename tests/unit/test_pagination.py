from datetime import UTC, datetime

import pytest

from visuaslide.config import ReportConfig
from visuaslide.layouts import build_default_layout
from visuaslide.models import AnalysisResult, AnalysisTable
from visuaslide.reporting import build_presentation_content
from visuaslide.update_plan import managed_object_id, plan_report_update


def _analysis(count):
    return AnalysisResult(
        run_id="synthetic-run",
        snapshot_id="a" * 64,
        created_at=datetime(2026, 11, 7, tzinfo=UTC),
        input_rows=3,
        accepted_rows=3,
        tables=(
            AnalysisTable(
                analysis_id="faculties",
                columns=("category", "frequency", "numerator", "denominator", "percentage"),
                rows=tuple(
                    (
                        f"Khoa {index}",
                        int(index < 3),
                        int(index < 3),
                        3,
                        1 / 3 if index < 3 else 0.0,
                    )
                    for index in range(count)
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("count", "sizes"), [(10, [10]), (11, [10, 1]), (13, [10, 3]), (20, [10, 10])]
)
def test_pages_preserve_complete_analysis_denominators_and_stable_ids(count, sizes):
    analysis = _analysis(count)
    content = build_presentation_content(analysis, ReportConfig())
    assert [len(table.rows) for table in content.tables] == sizes
    assert tuple(row for table in content.tables for row in table.rows) == analysis.tables[0].rows
    assert [len(chart.categories) for chart in content.charts] == sizes
    assert all(table.source_analysis_id == "faculties" for table in content.tables)
    assert all(row[3] == 3 for table in content.tables for row in table.rows)
    plan = plan_report_update(content)
    assert plan.mapping.entries == plan_report_update(content, plan.mapping).mapping.entries
    assert next(
        entry.object_id for entry in plan.mapping.entries if entry.object_key == "table:faculties"
    ) == managed_object_id("table:faculties")
    assert len(build_default_layout(content).slides) == len(sizes) + 2


def test_removing_continuation_page_removes_only_its_registered_objects():
    first = plan_report_update(build_presentation_content(_analysis(13), ReportConfig()))
    smaller = build_presentation_content(_analysis(9), ReportConfig())
    second = plan_report_update(smaller, first.mapping)
    assert {entry.kind for entry in second.removed} == {"text", "table", "chart"}
    assert len(second.removed) == 3
    assert all(
        "/page/2" in entry.object_key or entry.object_key.startswith("text:caption__page_")
        for entry in second.removed
    )
    assert {entry.object_id for entry in first.mapping.entries} - {
        entry.object_id for entry in second.mapping.entries
    } == {entry.object_id for entry in second.removed}


def test_continuation_keys_cannot_collide_with_another_analysis_id():
    analysis = _analysis(13)
    another = analysis.tables[0].model_copy(
        update={"analysis_id": "faculties_page_2", "rows": analysis.tables[0].rows[:1]}
    )
    content = build_presentation_content(
        analysis.model_copy(update={"tables": (*analysis.tables, another)}), ReportConfig()
    )
    plan = plan_report_update(content)
    keys = [entry.object_key for entry in plan.mapping.entries]
    assert len(keys) == len(set(keys))
    assert "table:faculties/page/2" in keys
    assert "table:faculties_page_2" in keys
