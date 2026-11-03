import pytest

from visuaslide.exceptions import PublishingError
from visuaslide.layouts import build_default_layout
from visuaslide.reporting import (
    ChartSeries,
    PresentationContent,
    ReportChart,
    ReportTable,
    ReportText,
)


def _content(category_count: int = 2) -> PresentationContent:
    categories = tuple(f"Nhóm {index}" for index in range(category_count))
    rows = tuple((category, index) for index, category in enumerate(categories))
    return PresentationContent(
        run_id="run-1",
        snapshot_id="a" * 64,
        title="Báo cáo khảo sát",
        locale="vi-VN",
        text_blocks=(
            ReportText(object_id="research_question", text="Câu hỏi nghiên cứu"),
            ReportText(
                object_id="caption_answers",
                text="Mô tả kết quả",
                source_analysis_id="answers",
            ),
            ReportText(object_id="conclusion", text="Kết luận do người dùng cung cấp"),
        ),
        tables=(
            ReportTable(
                object_id="table_answers",
                title="Answers",
                columns=("category", "frequency"),
                rows=rows,
                source_analysis_id="answers",
            ),
        ),
        charts=(
            ReportChart(
                object_id="chart_answers",
                title="Answers",
                categories=categories,
                series=(ChartSeries(label="Frequency", values=tuple(range(category_count))),),
                source_analysis_id="answers",
            ),
        ),
    )


def test_default_layout_is_widescreen_and_preserves_vietnamese_content() -> None:
    content = _content()

    layout = build_default_layout(content)

    assert layout.width_inches == pytest.approx(13.333333)
    assert layout.height_inches == 7.5
    assert layout.locale == "vi-VN"
    assert [slide.role for slide in layout.slides] == [
        "cover",
        "analysis",
        "conclusion",
    ]
    assert layout.slides[0].title == content.title
    assert layout.slides[1].table_ids == ("table_answers",)
    assert layout.slides[1].chart_ids == ("chart_answers",)
    assert layout.slides[1].text_ids == ("caption_answers",)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_content().model_copy(update={"title": "B" * 73}), "report title exceeds"),
        (_content(category_count=11), "chart chart_answers exceeds 10 categories"),
        (_content(category_count=19), "table table_answers exceeds 18 rows"),
        (
            _content().model_copy(
                update={"text_blocks": (ReportText(object_id="long_text", text="x" * 2401),)}
            ),
            "text object long_text exceeds",
        ),
    ],
)
def test_layout_rejects_overflow_without_truncating_content(
    content: PresentationContent, message: str
) -> None:
    with pytest.raises(PublishingError, match=message):
        build_default_layout(content)
