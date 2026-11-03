from visuaslide.reporting import (
    ChartSeries,
    PresentationContent,
    ReportChart,
    ReportTable,
    ReportText,
)
from visuaslide.update_plan import plan_report_update


def _content(*, count: int, title: str = "Survey") -> PresentationContent:
    return PresentationContent(
        run_id=f"run-{count}",
        snapshot_id="a" * 64,
        title=title,
        locale="vi-VN",
        text_blocks=(ReportText(object_id="sample_size", text=f"Valid responses: {count}"),),
        tables=(
            ReportTable(
                object_id="table_answers",
                title="Answers",
                columns=("category", "frequency"),
                rows=(("Yes", count),),
                source_analysis_id="answers",
            ),
        ),
        charts=(
            ReportChart(
                object_id="chart_answers",
                title="Answers",
                categories=("Yes",),
                series=(ChartSeries(label="Frequency", values=(count,)),),
                source_analysis_id="answers",
            ),
        ),
    )


def test_update_plan_creates_stable_object_ids_then_updates_content() -> None:
    first = plan_report_update(_content(count=3))
    second = plan_report_update(_content(count=4), first.mapping)
    first_ids = {operation.object_key: operation.object_id for operation in first.operations}
    second_ids = {operation.object_key: operation.object_id for operation in second.operations}
    actions = {operation.object_key: operation.action for operation in second.operations}

    assert all(operation.action == "create" for operation in first.operations)
    assert second_ids == first_ids
    assert actions["title:report"] == "unchanged"
    assert actions["table:answers"] == "update"
    assert actions["chart:answers"] == "update"
    assert actions["text:sample_size"] == "update"


def test_identical_content_plans_no_redundant_updates() -> None:
    first = plan_report_update(_content(count=3))
    second = plan_report_update(_content(count=3), first.mapping)

    assert all(operation.action == "unchanged" for operation in second.operations)
    assert first.mapping == second.mapping
