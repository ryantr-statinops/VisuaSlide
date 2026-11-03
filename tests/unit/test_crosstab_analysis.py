import pandas as pd
import pytest

from visuaslide.analysis import calculate_crosstab
from visuaslide.config import CrosstabAnalysis, VariableSchema


def _variables() -> tuple[VariableSchema, VariableSchema]:
    row = VariableSchema(
        name="group",
        source_header="Group",
        kind="categorical",
        categories=("A", "B", "C"),
    )
    column = VariableSchema(
        name="choice",
        source_header="Choice",
        kind="categorical",
        categories=("X", "Y", "Z"),
    )
    return row, column


@pytest.mark.parametrize(
    (
        "basis",
        "expected_first_row_denominators",
        "expected_empty_row_denominators",
        "expected_final_percentage",
    ),
    [
        ("row", (2, 2, 2), (0, 0, 0), None),
        ("column", (2, 2, 0), (2, 2, 0), None),
        ("all", (4, 4, 4), (4, 4, 4), 0.0),
    ],
)
def test_crosstab_keeps_category_order_and_uses_configured_basis(
    basis: str,
    expected_first_row_denominators: tuple[int, int, int],
    expected_empty_row_denominators: tuple[int, int, int],
    expected_final_percentage: float | None,
) -> None:
    row_variable, column_variable = _variables()
    frame = pd.DataFrame(
        {
            "group": ["A", "A", "A", "B", "B", None],
            "choice": ["X", "Y", None, "X", "Y", "X"],
        }
    )
    result = calculate_crosstab(
        frame,
        row_variable,
        column_variable,
        CrosstabAnalysis(
            id="group_by_choice",
            kind="crosstab",
            row_variable="group",
            column_variable="choice",
            percentage_basis=basis,
        ),
    )

    assert len(result.rows) == 9
    assert [(row[0], row[1]) for row in result.rows] == [
        (group, choice)
        for group in row_variable.categories
        for choice in column_variable.categories
    ]
    assert [row[2] for row in result.rows] == [1, 1, 0, 1, 1, 0, 0, 0, 0]
    assert [row[4] for row in result.rows[:3]] == list(expected_first_row_denominators)
    assert [row[4] for row in result.rows[6:]] == list(expected_empty_row_denominators)
    assert result.rows[-1][-1] == expected_final_percentage


def test_crosstab_undefined_percentage_when_no_complete_pairs_exist() -> None:
    row_variable, column_variable = _variables()
    result = calculate_crosstab(
        pd.DataFrame({"group": ["A", None], "choice": [None, "X"]}),
        row_variable,
        column_variable,
        CrosstabAnalysis(
            id="group_by_choice",
            kind="crosstab",
            row_variable="group",
            column_variable="choice",
            percentage_basis="all",
        ),
    )

    assert all(row[2] == 0 and row[4] == 0 and row[5] is None for row in result.rows)
