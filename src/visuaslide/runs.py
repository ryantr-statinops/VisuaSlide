"""Run manifests for reproducible analysis and recoverable publication."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from visuaslide import __version__
from visuaslide.config import ProjectConfig, StrictModel
from visuaslide.exceptions import StorageError
from visuaslide.models import RunStatus


class RunManifest(StrictModel):
    """Safe provenance and progress record; it deliberately excludes responses."""

    run_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    status: RunStatus
    stage: str
    created_at: datetime
    updated_at: datetime
    source_identity: dict[str, str | int]
    source_hash: str
    config_hash: str
    sdk_version: str
    template_version: str | None = None
    snapshot_id: str | None = None
    completed_steps: tuple[str, ...] = ()
    error_code: str | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run timestamps must include a timezone")
        return value.astimezone(UTC)

    @classmethod
    def start(cls, config: ProjectConfig) -> RunManifest:
        """Create an initial manifest with only source/config provenance."""
        source_identity: dict[str, str | int] = {
            "spreadsheet_id": config.source.spreadsheet_id,
            "sheet_id": config.source.sheet_id,
            "column_range": config.source.column_range,
            "header_row": config.source.header_row,
        }
        now = datetime.now(UTC)
        return cls(
            run_id=str(uuid.uuid4()),
            status=RunStatus.RUNNING,
            stage="initialized",
            created_at=now,
            updated_at=now,
            source_identity=source_identity,
            source_hash=_sha256(source_identity),
            config_hash=effective_config_hash(config),
            sdk_version=__version__,
            template_version="2",
        )


class RunStore:
    """Create, load, and atomically update project run manifests."""

    def __init__(self, project_dir: str | Path) -> None:
        self._root = Path(project_dir).resolve() / "runs"

    def create(self, config: ProjectConfig) -> RunManifest:
        manifest = RunManifest.start(config)
        path = self._path(manifest.run_id)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, manifest.model_dump_json().encode("utf-8"), replace=False)
        except OSError as exc:
            raise StorageError(f"Could not create run manifest {manifest.run_id}: {exc}") from exc
        return manifest

    def load(self, run_id: str) -> RunManifest:
        path = self._path(run_id)
        try:
            return RunManifest.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            raise StorageError(f"Could not load run manifest {run_id}: {exc}") from exc

    def save(self, manifest: RunManifest) -> None:
        """Atomically replace a manifest for its existing run ID."""
        path = self._path(manifest.run_id)
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if not path.is_file():
                raise StorageError(f"Run manifest {manifest.run_id} does not exist")
            _atomic_write(path, manifest.model_dump_json().encode("utf-8"), replace=True)
        except OSError as exc:
            raise StorageError(f"Could not update run manifest {manifest.run_id}: {exc}") from exc

    def _path(self, run_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(run_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise StorageError("run_id must be a UUID") from exc
        if normalized != run_id:
            raise StorageError("run_id must use lowercase canonical UUID text")
        return self._root / f"{normalized}.json"


def _sha256(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def effective_config_hash(config: ProjectConfig) -> str:
    """Return the canonical hash used to bind a run to its effective config."""
    payload = config.model_dump(mode="json", by_alias=True)
    # Omit additive defaults so configurations recorded by 0.1 remain replayable.
    for variable in payload["schema"]["variables"]:
        for name, default in (("aliases", {}), ("separator", ","), ("allowed_values", None)):
            if variable.get(name) == default:
                variable.pop(name, None)
    return _sha256(payload)


def _atomic_write(path: Path, content: bytes, *, replace: bool) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if replace:
            os.replace(temporary_path, path)
            temporary_path = None
        else:
            try:
                os.link(temporary_path, path)
            except PermissionError:
                if os.name != "nt":
                    raise
                # Windows rename refuses to replace an existing destination.
                os.rename(temporary_path, path)
                temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
