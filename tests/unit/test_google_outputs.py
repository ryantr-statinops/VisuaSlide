from unittest.mock import Mock

import pytest

from visuaslide.exceptions import PublishingError
from visuaslide.google_outputs import ManagedOutputStore, verify_managed_output


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
