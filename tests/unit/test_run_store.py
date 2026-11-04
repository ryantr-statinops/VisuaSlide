from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from visuaslide.config import ProjectConfig
from visuaslide.exceptions import StorageError
from visuaslide.models import RunStatus
from visuaslide.runs import RunManifest, RunStore


def _config() -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "source": {
                "spreadsheet_id": "synthetic",
                "sheet_id": 0,
                "column_range": "A:B",
            },
            "schema": {
                "variables": [
                    {
                        "name": "answer",
                        "source_header": "Answer",
                        "kind": "categorical",
                        "categories": ["yes", "no"],
                    }
                ]
            },
            "analysis": {
                "specifications": [
                    {
                        "id": "answer_count",
                        "kind": "frequency",
                        "variable": "answer",
                        "denominator": "non_missing",
                    }
                ]
            },
        }
    )


def test_run_store_records_provenance_without_response_values(tmp_path) -> None:
    store = RunStore(tmp_path)

    manifest = store.create(_config())
    serialized = (tmp_path / "runs" / f"{manifest.run_id}.json").read_text("utf-8")

    assert manifest.status == RunStatus.RUNNING
    assert manifest.source_identity["spreadsheet_id"] == "synthetic"
    assert len(manifest.source_hash) == 64
    assert len(manifest.config_hash) == 64
    assert '"response"' not in serialized
    assert store.load(manifest.run_id) == manifest


def test_run_store_atomically_persists_progress_updates(tmp_path) -> None:
    store = RunStore(tmp_path)
    manifest = store.create(_config())
    updated = manifest.model_copy(
        update={
            "status": RunStatus.READY,
            "stage": "analysis_complete",
            "updated_at": datetime(2026, 11, 3, 1, tzinfo=UTC),
            "completed_steps": ("source_read", "snapshot_saved", "analysis_complete"),
            "snapshot_id": "a" * 64,
        }
    )

    store.save(updated)

    assert store.load(manifest.run_id) == updated


def test_run_manifest_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="run timestamps"):
        RunManifest(
            run_id="00000000-0000-0000-0000-000000000001",
            status=RunStatus.RUNNING,
            stage="started",
            created_at=datetime(2026, 11, 3),
            updated_at=datetime(2026, 11, 3, tzinfo=UTC),
            source_identity={},
            source_hash="a" * 64,
            config_hash="b" * 64,
            sdk_version="0.1.0",
        )


def test_run_store_rejects_noncanonical_ids_and_unknown_updates(tmp_path) -> None:
    store = RunStore(tmp_path)
    with pytest.raises(StorageError, match="UUID"):
        store.load("../../run")
    with pytest.raises(StorageError, match="does not exist"):
        store.save(RunManifest.start(_config()))


def test_run_store_creates_manifest_on_windows_without_hard_links(tmp_path) -> None:
    store = RunStore(tmp_path)
    with patch("visuaslide.runs.os.link", side_effect=PermissionError("hard links disabled")):
        manifest = store.create(_config())
    assert store.load(manifest.run_id) == manifest
