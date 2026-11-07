import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from visuaslide.config import load_config
from visuaslide.snapshots import SourceSnapshot


@pytest.fixture
def multiselect_case(tmp_path):
    root = Path(__file__).parents[1]
    config = load_config(root / "examples/multiselect.example.toml").model_copy(
        update={"project_dir": tmp_path}
    )
    fixture = json.loads((root / "examples/multiselect.example.json").read_text(encoding="utf-8"))
    snapshot = SourceSnapshot.capture(
        config.source,
        headers=tuple(fixture["headers"]),
        rows=tuple(tuple(row) for row in fixture["rows"]),
        acquired_at=datetime(2026, 11, 7, tzinfo=UTC),
    )
    return config, snapshot
