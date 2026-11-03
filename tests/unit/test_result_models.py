from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from visuaslide.models import (
    AnalysisResult,
    AnalysisTable,
    RunResult,
    RunStatus,
    Statistic,
    ValidationIssue,
    ValidationReport,
)


def _analysis_result() -> AnalysisResult:
    return AnalysisResult(
        run_id="run-1",
        snapshot_id="snapshot-1",
        created_at=datetime(2026, 11, 3, tzinfo=UTC),
        input_rows=3,
        accepted_rows=2,
        statistics=(
            Statistic(name="yes_rate", value=0.5, numerator=1, denominator=2, unit="ratio"),
        ),
        tables=(
            AnalysisTable(
                analysis_id="answers",
                columns=("answer", "count"),
                rows=(("yes", 1), ("no", 1)),
            ),
        ),
    )


def test_analysis_result_round_trips_through_json() -> None:
    original = _analysis_result()

    restored = AnalysisResult.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.created_at.utcoffset().total_seconds() == 0


def test_validation_report_enforces_row_accounting_and_safe_issues() -> None:
    report = ValidationReport(
        snapshot_id="snapshot-1",
        input_rows=3,
        blank_rows=1,
        accepted_rows=1,
        invalid_rows=1,
        issues=(
            ValidationIssue(
                code="invalid_number",
                message="Expected a numeric value.",
                variable="score",
                source_row=4,
            ),
        ),
    )

    assert not report.is_valid
    assert "raw_value" not in report.model_dump()


def test_validation_report_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValidationError, match="input_rows must equal"):
        ValidationReport(
            snapshot_id="snapshot-1",
            input_rows=2,
            blank_rows=0,
            accepted_rows=1,
            invalid_rows=0,
        )


def test_analysis_table_rejects_mismatched_row_width() -> None:
    with pytest.raises(ValidationError, match="same width"):
        AnalysisTable(analysis_id="table", columns=("a", "b"), rows=((1,),))


@pytest.mark.parametrize(
    "values",
    [
        {"name": "rate", "value": 0.5, "numerator": 1},
        {"name": "rate", "value": 1.1, "numerator": 11, "denominator": 10},
        {"name": "rate", "value": 0.0, "numerator": 0, "denominator": 0},
    ],
)
def test_statistic_requires_valid_denominator_provenance(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Statistic.model_validate(values)


def test_run_result_requires_analysis_when_completed() -> None:
    with pytest.raises(ValidationError, match="completed runs require"):
        RunResult(
            run_id="run-1",
            status=RunStatus.COMPLETED,
            stage="complete",
            updated_at=datetime(2026, 11, 3, tzinfo=UTC),
        )


def test_completed_run_serializes_output_links_and_result() -> None:
    analysis = _analysis_result()
    result = RunResult(
        run_id=analysis.run_id,
        status=RunStatus.COMPLETED,
        stage="complete",
        updated_at=analysis.created_at,
        snapshot_id=analysis.snapshot_id,
        analysis=analysis,
        output_urls={"presentation": "https://slides.example.invalid/presentation"},
    )

    assert RunResult.model_validate_json(result.model_dump_json()) == result
