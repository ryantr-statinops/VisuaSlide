from pathlib import Path
from unittest.mock import Mock, patch

from visuaslide.config import load_config
from visuaslide.google_bootstrap import GoogleBootstrapper, project_template_layout
from visuaslide.google_outputs import GoogleOutputManager

ROOT = Path(__file__).parents[2]


def test_bootstrap_layout_uses_configured_analysis_identities() -> None:
    config = load_config(ROOT / "examples/survey.example.toml")
    layout = project_template_layout(config)
    assert [slide.slide_key for slide in layout.slides] == [
        "cover",
        "context",
        "analysis_study_year_counts",
        "analysis_tool_use_rate",
        "analysis_score_summary",
        "analysis_year_by_tool",
        "conclusion",
    ]
    assert layout.slides[4].chart_ids == ()


def test_bootstrap_copies_template_into_distinct_presentation() -> None:
    config = load_config(ROOT / "examples/survey.example.toml")
    with (
        patch("visuaslide.google_bootstrap.GoogleCredentialStore") as credentials,
        patch("visuaslide.google_bootstrap.build") as build,
        patch("visuaslide.google_bootstrap.GoogleOutputManager") as manager,
        patch("visuaslide.google_bootstrap.GoogleSlidesTemplate") as template,
    ):
        credentials.return_value.load.return_value = Mock()
        manager.return_value.bootstrap_workbook.return_value = "workbook-id"
        template.return_value.bootstrap.return_value = "template-id"
        manager.return_value.bootstrap_file.return_value = "presentation-id"
        result = GoogleBootstrapper(config).bootstrap_outputs()

    assert result == {
        "workbook": "workbook-id",
        "template": "template-id",
        "presentation": "presentation-id",
    }
    assert build.call_count == 2
    manager.return_value.bootstrap_file.assert_called_once_with(
        "presentation", "VisuaSlide survey report", copy_from="template-id"
    )


def test_presentation_copy_carries_separate_management_marker(tmp_path) -> None:
    drive = Mock()
    manager = GoogleOutputManager(drive, tmp_path, "source-id")
    project_id = manager.store.load_or_create().project_id
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}
    drive.files.return_value.copy.return_value.execute.return_value = {"id": "deck-id"}
    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "deck-id",
        "mimeType": "application/vnd.google-apps.presentation",
        "appProperties": {
            "visuaslide_project": project_id,
            "visuaslide_role": "presentation",
        },
    }

    assert manager.bootstrap_file("presentation", "Report", copy_from="template-id") == "deck-id"
    copy_kwargs = drive.files.return_value.copy.call_args.kwargs
    assert copy_kwargs["fileId"] == "template-id"
    assert copy_kwargs["body"]["appProperties"]["visuaslide_role"] == "presentation"
