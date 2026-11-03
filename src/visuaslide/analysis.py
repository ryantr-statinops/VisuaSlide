"""DuckDB-backed descriptive survey analysis functions."""

from __future__ import annotations

import duckdb
import pandas as pd

from visuaslide.config import FrequencyAnalysis, PercentageDenominator, VariableSchema
from visuaslide.exceptions import DataValidationError
from visuaslide.models import AnalysisTable


def calculate_frequency(
    frame: pd.DataFrame,
    variable: VariableSchema,
    specification: FrequencyAnalysis,
) -> AnalysisTable:
    """Calculate ordered category counts and percentages with explicit denominators."""
    if specification.variable != variable.name:
        raise ValueError("frequency specification and variable do not match")
    if variable.name not in frame.columns:
        raise DataValidationError("Frequency input is missing a prepared variable.")

    identifier = _quote_identifier(variable.name)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.register("survey_data", frame)
        counts = dict(
            connection.execute(
                f"SELECT {identifier}, COUNT(*) FROM survey_data "
                f"WHERE {identifier} IS NOT NULL GROUP BY {identifier}"
            ).fetchall()
        )
        denominator_query = (
            "COUNT(*)"
            if specification.denominator == PercentageDenominator.ALL_RESPONSES
            else f"COUNT({identifier})"
        )
        denominator = int(
            connection.execute(f"SELECT {denominator_query} FROM survey_data").fetchone()[0]
        )
    finally:
        connection.close()

    rows = []
    for category in variable.categories:
        count = int(counts.get(category, 0))
        percentage = count / denominator if denominator else None
        rows.append((category, count, count, denominator, percentage))
    return AnalysisTable(
        analysis_id=specification.id,
        columns=("category", "frequency", "numerator", "denominator", "percentage"),
        rows=tuple(rows),
    )


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'
