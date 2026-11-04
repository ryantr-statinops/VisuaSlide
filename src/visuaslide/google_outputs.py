"""Identity checks for application-managed Google output files."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from visuaslide.config import StrictModel
from visuaslide.exceptions import PublishingError, StorageError

OutputRole = Literal["workbook", "template", "presentation"]
MIME_TYPES = {
    "workbook": "application/vnd.google-apps.spreadsheet",
    "template": "application/vnd.google-apps.presentation",
    "presentation": "application/vnd.google-apps.presentation",
}


class ManagedOutputRegistry(StrictModel):
    """Local identity binding for one project and its managed Drive files."""

    project_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    files: dict[OutputRole, str] = Field(default_factory=dict)


class ManagedOutputStore:
    def __init__(self, project_dir: Path) -> None:
        self.path = Path(project_dir).resolve() / "google_outputs.json"

    def load_or_create(self) -> ManagedOutputRegistry:
        if self.path.is_file():
            try:
                return ManagedOutputRegistry.model_validate_json(self.path.read_bytes())
            except (OSError, ValueError) as exc:
                raise StorageError("Managed Google output registry is invalid.") from exc
        registry = ManagedOutputRegistry(project_id=str(uuid.uuid4()))
        self.save(registry)
        return registry

    def save(self, registry: ManagedOutputRegistry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent, delete=False) as file:
                temporary_path = Path(file.name)
                file.write(registry.model_dump_json().encode("utf-8"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise StorageError("Could not save managed Google output registry.") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def verify_managed_output(
    drive_service: Any,
    *,
    file_id: str,
    role: OutputRole,
    project_id: str,
    source_spreadsheet_id: str,
) -> None:
    """Reject source, wrong MIME type, trashed, and unmarked Drive files."""
    if file_id == source_spreadsheet_id:
        raise PublishingError("The survey source cannot be used as a report output.")
    try:
        file = (
            drive_service.files()
            .get(fileId=file_id, fields="id,mimeType,appProperties,trashed")
            .execute()
        )
    except Exception as exc:
        raise PublishingError("Could not verify the managed Google output file.") from exc
    properties = file.get("appProperties", {})
    if (
        file.get("id") != file_id
        or file.get("mimeType") != MIME_TYPES[role]
        or file.get("trashed", False)
        or properties.get("visuaslide_project") != project_id
        or properties.get("visuaslide_role") != role
    ):
        raise PublishingError("Google output identity or management marker does not match.")
