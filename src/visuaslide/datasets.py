"""Immutable storage for validated survey datasets in Parquet format."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from visuaslide.exceptions import StorageError
from visuaslide.models import ValidationReport


@dataclass(frozen=True)
class StoredDataset:
    """Location and dimensions of one persisted validated dataset."""

    snapshot_id: str
    path: Path
    rows: int
    columns: tuple[str, ...]


class DatasetStore:
    """Store validated pandas datasets without overwriting prior snapshots."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def save(
        self,
        snapshot_id: str,
        frame: pd.DataFrame,
        validation: ValidationReport,
    ) -> StoredDataset:
        """Persist a dataset only when its matching validation report is valid."""
        if snapshot_id != validation.snapshot_id:
            raise StorageError("Dataset snapshot ID does not match its validation report.")
        if not validation.is_valid:
            raise StorageError("Cannot persist a dataset with validation errors.")
        if len(frame) != validation.accepted_rows:
            raise StorageError("Dataset row count does not match accepted response count.")
        if len(frame.columns) != len(set(frame.columns)):
            raise StorageError("Dataset column names must be unique.")
        if not _is_snapshot_id(snapshot_id):
            raise StorageError("Dataset snapshot ID must be a SHA-256 hex digest.")

        target = self._root / f"{snapshot_id}.parquet"
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if target.exists():
                existing = pd.read_parquet(target)
                if not existing.equals(frame):
                    raise StorageError("Stored dataset content does not match this snapshot.")
                return StoredDataset(snapshot_id, target, len(existing), tuple(existing.columns))
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=self._root,
                    prefix=f".{snapshot_id}.",
                    suffix=".parquet.tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                frame.to_parquet(temporary_path, index=False, engine="pyarrow")
                with temporary_path.open("rb+") as file:
                    os.fsync(file.fileno())
                try:
                    os.link(temporary_path, target)
                except PermissionError:
                    if os.name != "nt":
                        raise
                    # Windows rename does not replace an existing destination.
                    os.rename(temporary_path, target)
                    temporary_path = None
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
            return StoredDataset(snapshot_id, target, len(frame), tuple(frame.columns))
        except StorageError:
            raise
        except (OSError, ValueError, ImportError) as exc:
            raise StorageError(f"Could not persist validated dataset {snapshot_id}: {exc}") from exc

    def load(self, snapshot_id: str) -> pd.DataFrame:
        """Load a persisted dataset by its validated snapshot ID."""
        if not _is_snapshot_id(snapshot_id):
            raise StorageError("Dataset snapshot ID must be a SHA-256 hex digest.")
        path = self._root / f"{snapshot_id}.parquet"
        try:
            return pd.read_parquet(path, engine="pyarrow")
        except (OSError, ValueError, ImportError) as exc:
            raise StorageError(f"Could not load validated dataset {snapshot_id}: {exc}") from exc


def _is_snapshot_id(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)
