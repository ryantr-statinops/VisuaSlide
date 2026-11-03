import math

import pandas as pd

from visuaslide.analysis import calculate_numeric_summary
from visuaslide.config import NumericSummaryAnalysis, VariableSchema


def _variable() -> VariableSchema:
    return VariableSchema(name="score", source_header="Score", kind="numeric")


def _specification() -> NumericSummaryAnalysis:
    return NumericSummaryAnalysis(id="score_summary", kind="numeric_summary", variable="score")


def test_numeric_summary_uses_sample_standard_deviation_and_excludes_missing() -> None:
    result = calculate_numeric_summary(
        pd.DataFrame({"score": [1.0, 3.0, None]}), _variable(), _specification()
    )
    values = {row[0]: row[1] for row in result.rows}

    assert values["count"] == 2
    assert values["mean"] == 2.0
    assert values["median"] == 2.0
    assert values["min"] == 1.0
    assert values["max"] == 3.0
    assert values["sample_stddev"] == math.sqrt(2)


def test_numeric_summary_returns_undefined_stddev_for_fewer_than_two_values() -> None:
    one_value = calculate_numeric_summary(
        pd.DataFrame({"score": [5.0, None]}), _variable(), _specification()
    )
    no_values = calculate_numeric_summary(
        pd.DataFrame({"score": [None, None]}), _variable(), _specification()
    )

    assert {row[0]: row[1] for row in one_value.rows}["sample_stddev"] is None
    assert {row[0]: row[1] for row in no_values.rows}["sample_stddev"] is None
