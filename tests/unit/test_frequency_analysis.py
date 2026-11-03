import pandas as pd
import pytest

from visuaslide.analysis import calculate_frequency
from visuaslide.config import FrequencyAnalysis, VariableSchema
from visuaslide.exceptions import DataValidationError


def _variable() -> VariableSchema:
    return VariableSchema(
        name="answer",
        source_header="Answer",
        kind="categorical",
        categories=("yes", "no", "not observed"),
    )


@pytest.mark.parametrize(
    ("denominator", "expected_denominator", "expected_percentages"),
    [
        ("non_missing", 3, (2 / 3, 1 / 3, 0.0)),
        ("all_responses", 4, (0.5, 0.25, 0.0)),
    ],
)
def test_frequency_analysis_keeps_declared_category_order_and_denominator(
    denominator: str, expected_denominator: int, expected_percentages: tuple[float, ...]
) -> None:
    variable = _variable()
    spec = FrequencyAnalysis(
        id="answer_frequency", kind="frequency", variable="answer", denominator=denominator
    )
    result = calculate_frequency(
        pd.DataFrame({"answer": ["yes", "yes", "no", None]}), variable, spec
    )

    assert result.columns == ("category", "frequency", "numerator", "denominator", "percentage")
    assert [row[0] for row in result.rows] == list(variable.categories)
    assert [row[1] for row in result.rows] == [2, 1, 0]
    assert [row[2] for row in result.rows] == [2, 1, 0]
    assert [row[3] for row in result.rows] == [expected_denominator] * 3
    assert [row[4] for row in result.rows] == list(expected_percentages)


def test_frequency_analysis_returns_undefined_percentages_for_zero_denominator() -> None:
    result = calculate_frequency(
        pd.DataFrame({"answer": [None, None]}),
        _variable(),
        FrequencyAnalysis(
            id="answer_frequency", kind="frequency", variable="answer", denominator="non_missing"
        ),
    )

    assert all(row[1:] == (0, 0, 0, None) for row in result.rows)


def test_frequency_analysis_requires_prepared_column() -> None:
    with pytest.raises(DataValidationError, match="prepared variable"):
        calculate_frequency(
            pd.DataFrame({"other": ["yes"]}),
            _variable(),
            FrequencyAnalysis(
                id="answer_frequency",
                kind="frequency",
                variable="answer",
                denominator="non_missing",
            ),
        )
