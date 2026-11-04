from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from visuaslide.config import SourceConfig
from visuaslide.exceptions import StorageError
from visuaslide.snapshots import SourceSnapshot
from visuaslide.storage import SnapshotStore


def _snapshot() -> SourceSnapshot:
    return SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:B"),
        headers=("Response ID", "Score"),
        rows=(("r001", 8),),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )


def test_snapshot_store_round_trips_and_deduplicates_identical_content(tmp_path) -> None:
    store = SnapshotStore(tmp_path)

    first = store.save(_snapshot())
    second = store.save(_snapshot())

    assert first == second
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 1
    assert store.load(first.snapshot_id) == first


def test_snapshot_store_assigns_a_different_id_when_content_changes(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    first = store.save(_snapshot())
    changed = SourceSnapshot.capture(
        SourceConfig(spreadsheet_id="synthetic", sheet_id=0, column_range="A:B"),
        headers=("Response ID", "Score"),
        rows=(("r001", 9),),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )

    second = store.save(changed)

    assert first.snapshot_id != second.snapshot_id
    assert len(list((tmp_path / "snapshots").glob("*.json"))) == 2


def test_snapshot_store_detects_modified_snapshot_bytes(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    stored = store.save(_snapshot())
    path = tmp_path / "snapshots" / f"{stored.snapshot_id}.json"
    path.write_bytes(path.read_bytes().replace(b'"Score"', b'"Grade"'))

    with pytest.raises(StorageError):
        store.load(stored.snapshot_id)


def test_snapshot_store_rejects_path_traversal_ids(tmp_path) -> None:
    with pytest.raises(StorageError, match="lowercase SHA-256"):
        SnapshotStore(tmp_path).load("../outside")


def test_snapshot_store_saves_on_windows_when_hard_links_are_unavailable(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    with patch("visuaslide.storage.os.link", side_effect=PermissionError("hard links disabled")):
        stored = store.save(_snapshot())
    assert store.load(stored.snapshot_id) == stored


def test_snapshot_store_does_not_replace_existing_snapshot_on_rename_race(tmp_path) -> None:
    store = SnapshotStore(tmp_path)
    stored = store.save(_snapshot())
    existing = tmp_path / "snapshots" / f"{stored.snapshot_id}.json"
    original = existing.read_bytes()
    with patch("visuaslide.storage.os.link", side_effect=PermissionError("hard links disabled")):
        with patch("visuaslide.storage.os.rename", side_effect=FileExistsError):
            from visuaslide.storage import _atomic_create

            _atomic_create(existing, b"different")
    assert existing.read_bytes() == original
