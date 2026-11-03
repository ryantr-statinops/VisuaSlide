import pytest

from visuaslide.exceptions import OutputReconciliationError, PublishingError
from visuaslide.publisher import FakeReportPublisher
from visuaslide.reporting import (
    ChartSeries,
    PresentationContent,
    ReportChart,
    ReportTable,
    ReportText,
)
from visuaslide.update_plan import plan_report_update


def _content(value: int, title: str = "Survey") -> PresentationContent:
    return PresentationContent(
        run_id=f"run-{value}",
        snapshot_id="a" * 64,
        title=title,
        locale="vi-VN",
        text_blocks=(
            ReportText(
                object_id="caption_answer",
                text=f"Answer count: {value}",
                source_analysis_id="answer",
            ),
        ),
        tables=(
            ReportTable(
                object_id="table_answer",
                title="Answer",
                columns=("category", "frequency"),
                rows=(("Yes", value),),
                source_analysis_id="answer",
            ),
        ),
        charts=(
            ReportChart(
                object_id="chart_answer",
                title="Answer",
                categories=("Yes",),
                series=(ChartSeries(label="Frequency", values=(value,)),),
                source_analysis_id="answer",
            ),
        ),
    )


def test_fake_publisher_creates_then_updates_stable_workbook_and_deck_objects() -> None:
    publisher = FakeReportPublisher()
    first = publisher.publish(_content(3))
    first_ids = {item.object_key: item.object_id for item in first.plan.operations}
    second = publisher.publish(_content(4))
    second_ids = {item.object_key: item.object_id for item in second.plan.operations}

    assert all(item.action == "create" for item in first.plan.operations)
    assert second_ids == first_ids
    assert {item.action for item in second.plan.operations} == {"unchanged", "update"}
    assert second.managed_object_count == first.managed_object_count == 4
    chart = next(item for item in second.plan.operations if item.kind == "chart")
    assert chart.payload["series"][0]["values"] == [4]


def test_fake_publisher_rejects_layout_overflow_before_mutating_output() -> None:
    publisher = FakeReportPublisher()
    publisher.publish(_content(3))
    existing_state = publisher.objects
    existing_mapping = publisher.mapping

    with pytest.raises(PublishingError, match="report title exceeds"):
        publisher.publish(_content(4, title="Very long " * 10))

    assert publisher.objects == existing_state
    assert publisher.mapping == existing_mapping


def test_fake_publisher_stops_when_create_identity_has_different_payload() -> None:
    publisher = FakeReportPublisher()
    content = _content(3)
    plan = plan_report_update(content)
    operation = plan.operations[0]
    publisher._slide_objects[operation.object_id] = {"text": "unrecognized content"}

    with pytest.raises(OutputReconciliationError, match="cannot be reconciled safely"):
        publisher.publish_step("slides", content, plan)

    assert publisher.objects[operation.object_id] == {"text": "unrecognized content"}
