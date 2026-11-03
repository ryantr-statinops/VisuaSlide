import pytest
from pydantic import ValidationError

from visuaslide.config import AnalysisConfig, ProjectConfig


def test_analysis_config_accepts_each_supported_analysis_kind() -> None:
    config = AnalysisConfig.model_validate(
        {
            "specifications": [
                {
                    "id": "year_counts",
                    "kind": "frequency",
                    "variable": "study_year",
                    "denominator": "all_responses",
                },
                {"id": "score_stats", "kind": "numeric_summary", "variable": "score"},
                {
                    "id": "year_by_score_band",
                    "kind": "crosstab",
                    "row_variable": "study_year",
                    "column_variable": "score_band",
                    "percentage_basis": "row",
                },
            ]
        }
    )

    assert [specification.kind for specification in config.specifications] == [
        "frequency",
        "numeric_summary",
        "crosstab",
    ]


@pytest.mark.parametrize(
    "specifications",
    [
        [],
        [
            {"id": "counts", "kind": "frequency", "variable": "year"},
        ],
        [
            {
                "id": "same_variable",
                "kind": "crosstab",
                "row_variable": "year",
                "column_variable": "year",
                "percentage_basis": "row",
            }
        ],
        [
            {"id": "counts", "kind": "numeric_summary", "variable": "score"},
            {
                "id": "counts",
                "kind": "frequency",
                "variable": "year",
                "denominator": "all_responses",
            },
        ],
        [
            {
                "id": "counts",
                "kind": "frequency",
                "variable": "year",
                "denominator": "arbitrary",
            }
        ],
    ],
)
def test_analysis_config_rejects_missing_or_ambiguous_policy(
    specifications: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        AnalysisConfig(specifications=specifications)


def test_project_config_rejects_analysis_reference_with_wrong_variable_kind() -> None:
    with pytest.raises(ValidationError, match="requires a numeric variable"):
        ProjectConfig.model_validate(
            {
                "source": {
                    "spreadsheet_id": "synthetic",
                    "sheet_id": 0,
                    "column_range": "A:B",
                },
                "schema": {
                    "variables": [
                        {
                            "name": "year",
                            "source_header": "Year",
                            "kind": "categorical",
                            "categories": ["Year 1", "Year 2"],
                        }
                    ]
                },
                "analysis": {
                    "specifications": [
                        {"id": "year_stats", "kind": "numeric_summary", "variable": "year"}
                    ]
                },
            }
        )
