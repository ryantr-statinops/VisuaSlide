import pytest
from pydantic import ValidationError

from visuaslide.config import ProjectConfig, ReportConfig


def _project_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source": {
            "spreadsheet_id": "survey-source",
            "sheet_id": 0,
            "column_range": "A:B",
        },
        "schema": {
            "variables": [
                {
                    "name": "choice",
                    "source_header": "Choice",
                    "kind": "categorical",
                    "categories": ["yes", "no"],
                }
            ]
        },
        "analysis": {
            "specifications": [
                {
                    "id": "choice_counts",
                    "kind": "frequency",
                    "variable": "choice",
                    "denominator": "non_missing",
                }
            ]
        },
    }
    payload.update(overrides)
    return payload


def test_report_defaults_are_localized_and_outputs_can_be_bootstrapped_later() -> None:
    config = ProjectConfig.model_validate(_project_payload())

    assert config.report.locale == "vi-VN"
    assert config.report.display_timezone == "Asia/Ho_Chi_Minh"
    assert config.output.reporting_spreadsheet_id is None


def test_report_metadata_strips_title_and_keeps_author_content() -> None:
    report = ReportConfig(
        title="  Student survey  ",
        research_question="Which options are most common?",
        sampling_method="User supplied sampling description",
    )

    assert report.title == "Student survey"
    assert report.research_question == "Which options are most common?"
    assert report.sampling_method == "User supplied sampling description"


@pytest.mark.parametrize("value", ["", "   "])
def test_report_rejects_blank_required_metadata(value: str) -> None:
    with pytest.raises(ValidationError):
        ReportConfig(title=value)


@pytest.mark.parametrize(
    "output",
    [
        {"reporting_spreadsheet_id": "survey-source"},
        {
            "reporting_spreadsheet_id": "output-a",
            "template_presentation_id": "output-a",
        },
        {"presentation_id": "  "},
    ],
)
def test_project_rejects_output_ids_that_can_overwrite_source_or_collide(
    output: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(_project_payload(output=output))
