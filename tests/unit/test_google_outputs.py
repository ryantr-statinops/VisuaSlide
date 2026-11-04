from pathlib import Path
from unittest.mock import Mock

import pytest

from visuaslide.config import load_config
from visuaslide.exceptions import PublishingError
from visuaslide.google_outputs import (
    GoogleOutputManager,
    ManagedOutputStore,
    verify_configured_output_ids,
    verify_managed_output,
)


def _drive(file):
    service = Mock()
    service.files.return_value.get.return_value.execute.return_value = file
    return service


def test_registry_project_identity_survives_a_new_process(tmp_path) -> None:
    store = ManagedOutputStore(tmp_path)
    first = store.load_or_create()
    second = ManagedOutputStore(tmp_path).load_or_create()
    assert second.project_id == first.project_id
    assert second.files == {}


def test_configured_output_id_must_match_managed_registry(tmp_path) -> None:
    config = load_config(Path(__file__).parents[2] / "examples/survey.example.toml")
    config = config.model_copy(
        update={"output": config.output.model_copy(update={"reporting_spreadsheet_id": "other"})}
    )
    registry = ManagedOutputStore(tmp_path).load_or_create()
    with pytest.raises(PublishingError, match="does not match"):
        verify_configured_output_ids(config, registry)


def test_output_verification_requires_correct_marker_and_file_type() -> None:
    file = {
        "id": "workbook-id",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "appProperties": {"visuaslide_project": "project-id", "visuaslide_role": "workbook"},
    }
    verify_managed_output(
        _drive(file),
        file_id="workbook-id",
        role="workbook",
        project_id="project-id",
        source_spreadsheet_id="source-id",
    )
    with pytest.raises(PublishingError, match="marker does not match"):
        verify_managed_output(
            _drive({**file, "appProperties": {}}),
            file_id="workbook-id",
            role="workbook",
            project_id="project-id",
            source_spreadsheet_id="source-id",
        )


def test_output_verification_rejects_source_before_drive_read() -> None:
    drive = Mock()
    with pytest.raises(PublishingError, match="survey source"):
        verify_managed_output(
            drive,
            file_id="source-id",
            role="workbook",
            project_id="project-id",
            source_spreadsheet_id="source-id",
        )
    drive.files.assert_not_called()


def test_workbook_bootstrap_creates_once_and_reuses_verified_identity(tmp_path) -> None:
    drive = Mock()
    manager = GoogleOutputManager(drive, tmp_path, "source-id")
    project_id = manager.store.load_or_create().project_id
    drive.files.return_value.list.return_value.execute.return_value = {"files": []}
    drive.files.return_value.create.return_value.execute.return_value = {"id": "workbook-id"}
    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "workbook-id",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "appProperties": {"visuaslide_project": project_id, "visuaslide_role": "workbook"},
    }

    assert manager.bootstrap_workbook() == "workbook-id"
    assert manager.bootstrap_workbook() == "workbook-id"
    assert manager.store.load_or_create().files["workbook"] == "workbook-id"
    drive.files.return_value.create.assert_called_once()


def test_workbook_timeout_reconciles_one_marked_file(tmp_path) -> None:
    drive = Mock()
    manager = GoogleOutputManager(drive, tmp_path, "source-id")
    project_id = manager.store.load_or_create().project_id
    drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": []},
        {"files": [{"id": "workbook-id"}]},
    ]
    drive.files.return_value.create.return_value.execute.side_effect = TimeoutError("private")
    drive.files.return_value.get.return_value.execute.return_value = {
        "id": "workbook-id",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "appProperties": {"visuaslide_project": project_id, "visuaslide_role": "workbook"},
    }

    assert manager.bootstrap_workbook() == "workbook-id"
    assert manager.store.load_or_create().files["workbook"] == "workbook-id"
