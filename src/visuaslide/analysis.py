"""DuckDB-backed descriptive survey analysis functions."""

from __future__ import annotations

import duckdb
import pandas as pd

from visuaslide.config import (
    CrosstabAnalysis,
    FrequencyAnalysis,
    NumericSummaryAnalysis,
    PercentageBasis,
    PercentageDenominator,
    VariableKind,
    VariableSchema,
)
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


def calculate_numeric_summary(
    frame: pd.DataFrame,
    variable: VariableSchema,
    specification: NumericSummaryAnalysis,
) -> AnalysisTable:
    """Calculate descriptive numeric statistics with sample standard deviation."""
    if specification.variable != variable.name or variable.kind != VariableKind.NUMERIC:
        raise ValueError("numeric summary specification and variable do not match")
    if variable.name not in frame.columns:
        raise DataValidationError("Numeric summary input is missing a prepared variable.")

    identifier = _quote_identifier(variable.name)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.register("survey_data", frame)
        count, mean, median, minimum, maximum, sample_stddev = connection.execute(
            "SELECT "
            f"COUNT({identifier}), AVG({identifier}), MEDIAN({identifier}), "
            f"MIN({identifier}), MAX({identifier}), STDDEV_SAMP({identifier}) "
            "FROM survey_data"
        ).fetchone()
    finally:
        connection.close()

    numeric_count = int(count)
    return AnalysisTable(
        analysis_id=specification.id,
        columns=("statistic", "value", "n"),
        rows=(
            ("count", numeric_count, numeric_count),
            ("mean", float(mean) if mean is not None else None, numeric_count),
            ("median", float(median) if median is not None else None, numeric_count),
            ("min", float(minimum) if minimum is not None else None, numeric_count),
            ("max", float(maximum) if maximum is not None else None, numeric_count),
            (
                "sample_stddev",
                float(sample_stddev) if numeric_count >= 2 and sample_stddev is not None else None,
                numeric_count,
            ),
        ),
    )


def calculate_crosstab(
    frame: pd.DataFrame,
    row_variable: VariableSchema,
    column_variable: VariableSchema,
    specification: CrosstabAnalysis,
) -> AnalysisTable:
    """Calculate a configured crosstab over complete, nonmissing category pairs."""
    if (
        specification.row_variable != row_variable.name
        or specification.column_variable != column_variable.name
        or row_variable.kind != VariableKind.CATEGORICAL
        or column_variable.kind != VariableKind.CATEGORICAL
    ):
        raise ValueError("crosstab specification and variables do not match")
    if row_variable.name not in frame.columns or column_variable.name not in frame.columns:
        raise DataValidationError("Crosstab input is missing a prepared variable.")

    row_identifier = _quote_identifier(row_variable.name)
    column_identifier = _quote_identifier(column_variable.name)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.register("survey_data", frame)
        counts = {
            (row_category, column_category): int(count)
            for row_category, column_category, count in connection.execute(
                "SELECT "
                f"{row_identifier}, {column_identifier}, COUNT(*) "
                "FROM survey_data "
                f"WHERE {row_identifier} IS NOT NULL AND {column_identifier} IS NOT NULL "
                f"GROUP BY {row_identifier}, {column_identifier}"
            ).fetchall()
        }
    finally:
        connection.close()

    row_totals = {
        row_category: sum(
            int(counts.get((row_category, column_category), 0))
            for column_category in column_variable.categories
        )
        for row_category in row_variable.categories
    }
    column_totals = {
        column_category: sum(
            int(counts.get((row_category, column_category), 0))
            for row_category in row_variable.categories
        )
        for column_category in column_variable.categories
    }
    total = sum(row_totals.values())

    result_rows = []
    for row_category in row_variable.categories:
        for column_category in column_variable.categories:
            count = int(counts.get((row_category, column_category), 0))
            denominator = {
                PercentageBasis.ROW: row_totals[row_category],
                PercentageBasis.COLUMN: column_totals[column_category],
                PercentageBasis.ALL: total,
            }[specification.percentage_basis]
            result_rows.append(
                (
                    row_category,
                    column_category,
                    count,
                    count,
                    denominator,
                    count / denominator if denominator else None,
                )
            )
    return AnalysisTable(
        analysis_id=specification.id,
        columns=(
            "row_category",
            "column_category",
            "frequency",
            "numerator",
            "denominator",
            "percentage",
        ),
        rows=tuple(result_rows),
    )


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'
