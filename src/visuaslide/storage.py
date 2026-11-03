"""Atomic local persistence for private run artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from visuaslide.exceptions import StorageError
from visuaslide.snapshots import SourceSnapshot, StoredSnapshot


class SnapshotStore:
    """Store immutable source snapshots under a project runtime directory."""

    def __init__(self, project_dir: str | Path) -> None:
        self._root = Path(project_dir).resolve() / "snapshots"

    def save(self, snapshot: SourceSnapshot) -> StoredSnapshot:
        """Atomically save or return an existing identical snapshot."""
        serialized_snapshot = snapshot.model_dump(mode="json")
        content = _canonical_json(serialized_snapshot)
        content_hash = hashlib.sha256(content).hexdigest()
        stored = StoredSnapshot(
            snapshot_id=content_hash,
            content_hash=content_hash,
            snapshot=snapshot,
        )
        target = self._root / f"{stored.snapshot_id}.json"
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if target.exists():
                return self.load(stored.snapshot_id)
            _atomic_create(target, _canonical_json(stored.model_dump(mode="json")))
            return stored
        except (OSError, ValueError) as exc:
            raise StorageError(f"Could not store snapshot {stored.snapshot_id}: {exc}") from exc

    def load(self, snapshot_id: str) -> StoredSnapshot:
        """Load a snapshot and verify its content hash and requested ID."""
        if len(snapshot_id) != 64 or any(char not in "0123456789abcdef" for char in snapshot_id):
            raise StorageError("snapshot_id must be a lowercase SHA-256 digest")
        path = self._root / f"{snapshot_id}.json"
        try:
            envelope = StoredSnapshot.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            raise StorageError(f"Could not load snapshot {snapshot_id}: {exc}") from exc
        actual_hash = hashlib.sha256(
            _canonical_json(envelope.snapshot.model_dump(mode="json"))
        ).hexdigest()
        if envelope.content_hash != actual_hash or envelope.snapshot_id != actual_hash:
            raise StorageError(f"Snapshot {snapshot_id} failed integrity verification")
        if snapshot_id != envelope.snapshot_id:
            raise StorageError("requested snapshot ID does not match the stored record")
        return envelope


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _atomic_create(target: Path, content: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        try:
            os.link(temporary_path, target)
        except FileExistsError:
            pass
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
