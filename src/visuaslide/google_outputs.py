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
from visuaslide.locking import ProjectLock
from visuaslide.update_plan import ManagedObjectMap

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
    mapping: ManagedObjectMap = Field(default_factory=ManagedObjectMap)


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


class GoogleOutputManager:
    """Create and reconcile managed Drive files without duplicating uncertain creates."""

    def __init__(self, drive_service: Any, project_dir: Path, source_spreadsheet_id: str) -> None:
        self.drive = drive_service
        self.project_dir = Path(project_dir)
        self.source_spreadsheet_id = source_spreadsheet_id
        self.store = ManagedOutputStore(project_dir)

    def bootstrap_workbook(self) -> str:
        """Return the app-managed reporting workbook, creating it once if needed."""
        return self.bootstrap_file("workbook", "VisuaSlide reporting workbook")

    def bootstrap_file(self, role: OutputRole, name: str, *, copy_from: str | None = None) -> str:
        """Return or create one marked file, reconciling an uncertain create."""
        with ProjectLock(self.project_dir):
            registry = self.store.load_or_create()
            existing = registry.files.get(role)
            if existing:
                self._verify(existing, role, registry.project_id)
                return existing

            found = self._find_marked(role, registry.project_id)
            if found is None:
                properties = {
                    "visuaslide_project": registry.project_id,
                    "visuaslide_role": role,
                }
                try:
                    body = {"name": name, "mimeType": MIME_TYPES[role], "appProperties": properties}
                    if copy_from:
                        response = (
                            self.drive.files()
                            .copy(fileId=copy_from, body=body, fields="id")
                            .execute()
                        )
                    else:
                        response = self.drive.files().create(body=body, fields="id").execute()
                    found = response.get("id")
                except Exception as exc:
                    found = self._find_marked(role, registry.project_id)
                    if found is None:
                        raise PublishingError(
                            "Google output creation result is uncertain; "
                            "no managed file could be reconciled."
                        ) from exc
            if found is None:
                raise PublishingError("Google output creation returned no managed file ID.")
            self._verify(found, role, registry.project_id)
            updated_files = {**registry.files, role: found}
            self.store.save(registry.model_copy(update={"files": updated_files}))
            return found

    def _verify(self, file_id: str, role: OutputRole, project_id: str) -> None:
        verify_managed_output(
            self.drive,
            file_id=file_id,
            role=role,
            project_id=project_id,
            source_spreadsheet_id=self.source_spreadsheet_id,
        )

    def _find_marked(self, role: OutputRole, project_id: str) -> str | None:
        query = (
            f"appProperties has {{ key='visuaslide_project' and value='{project_id}' }} "
            f"and appProperties has {{ key='visuaslide_role' and value='{role}' }} "
            "and trashed = false"
        )
        try:
            result = (
                self.drive.files()
                .list(q=query, fields="nextPageToken,files(id,mimeType,appProperties)", pageSize=2)
                .execute()
            )
        except Exception as exc:
            raise PublishingError("Could not reconcile managed Google output creation.") from exc
        files = result.get("files", [])
        if len(files) > 1 or result.get("nextPageToken"):
            raise PublishingError("Multiple managed Google outputs match one project role.")
        return files[0]["id"] if files else None
