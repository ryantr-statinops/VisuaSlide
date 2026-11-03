from datetime import UTC, datetime

from visuaslide.config import ReportConfig
from visuaslide.models import AnalysisResult, AnalysisTable
from visuaslide.reporting import build_presentation_content


def _analysis() -> AnalysisResult:
    return AnalysisResult(
        run_id="run-1",
        snapshot_id="a" * 64,
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
        input_rows=5,
        accepted_rows=4,
        tables=(
            AnalysisTable(
                analysis_id="tool_use",
                columns=("category", "frequency", "numerator", "denominator", "percentage"),
                rows=(("Yes", 3, 3, 4, 0.75), ("No", 1, 1, 4, 0.25)),
            ),
            AnalysisTable(
                analysis_id="year_by_tool",
                columns=(
                    "row_category",
                    "column_category",
                    "frequency",
                    "numerator",
                    "denominator",
                    "percentage",
                ),
                rows=(("Year 1", "Yes", 2, 2, 2, 1.0), ("Year 1", "No", 0, 0, 2, 0.0)),
            ),
            AnalysisTable(
                analysis_id="score_summary",
                columns=("statistic", "value", "n"),
                rows=(("mean", 8.0, 4), ("sample_stddev", 1.5, 4)),
            ),
        ),
    )


def test_report_content_projects_tables_charts_and_captions_from_analysis() -> None:
    analysis = _analysis()
    content = build_presentation_content(
        analysis,
        ReportConfig(
            title="Khảo sát",
            research_question="Câu hỏi nghiên cứu",
            conclusion="Kết luận do người dùng cung cấp",
        ),
    )
    by_id = {table.source_analysis_id: table for table in content.tables}
    chart_by_id = {chart.source_analysis_id: chart for chart in content.charts}
    text_by_id = {
        block.source_analysis_id: block for block in content.text_blocks if block.source_analysis_id
    }

    assert content.title == "Khảo sát"
    assert content.run_id == analysis.run_id
    assert by_id["tool_use"].rows == analysis.tables[0].rows
    assert chart_by_id["tool_use"].categories == ("Yes", "No")
    assert chart_by_id["tool_use"].series[0].values == (3, 1)
    assert chart_by_id["year_by_tool"].series[0].values == (2,)
    assert "percentage: 0.75" in text_by_id["tool_use"].text
    assert "statistic: sample_stddev, value: 1.5" in text_by_id["score_summary"].text
    assert any(block.text == "Valid responses: 4" for block in content.text_blocks)
    assert any(block.text == "Kết luận do người dùng cung cấp" for block in content.text_blocks)
    assert "score_summary" not in chart_by_id
