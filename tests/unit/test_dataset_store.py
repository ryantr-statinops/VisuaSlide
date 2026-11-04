from unittest.mock import patch

import pandas as pd
import pytest

from visuaslide.datasets import DatasetStore
from visuaslide.exceptions import StorageError
from visuaslide.models import ValidationReport

SNAPSHOT_ID = "a" * 64


def _valid_report() -> ValidationReport:
    return ValidationReport(
        snapshot_id=SNAPSHOT_ID,
        input_rows=2,
        blank_rows=0,
        accepted_rows=2,
        invalid_rows=0,
    )


def test_dataset_store_round_trips_parquet_and_keeps_snapshot_identity(tmp_path) -> None:
    frame = pd.DataFrame({"answer": pd.Series(["yes", "no"], dtype="string"), "score": [1.0, 2.5]})
    store = DatasetStore(tmp_path)

    stored = store.save(SNAPSHOT_ID, frame, _valid_report())
    loaded = store.load(SNAPSHOT_ID)

    assert stored.snapshot_id == SNAPSHOT_ID
    assert stored.rows == 2
    assert stored.columns == ("answer", "score")
    pd.testing.assert_frame_equal(loaded, frame)
    assert store.save(SNAPSHOT_ID, frame, _valid_report()) == stored


@pytest.mark.parametrize(
    ("snapshot_id", "frame", "report", "message"),
    [
        (SNAPSHOT_ID, pd.DataFrame({"answer": ["yes"]}), _valid_report(), "row count"),
        (
            SNAPSHOT_ID,
            pd.DataFrame({"answer": ["yes", "no"]}),
            ValidationReport(
                snapshot_id=SNAPSHOT_ID,
                input_rows=2,
                blank_rows=0,
                accepted_rows=1,
                invalid_rows=1,
                issues=({"code": "invalid_value", "message": "Invalid value"},),
            ),
            "validation errors",
        ),
        ("b" * 64, pd.DataFrame({"answer": ["yes", "no"]}), _valid_report(), "does not match"),
    ],
)
def test_dataset_store_rejects_unvalidated_or_inconsistent_frames(
    tmp_path, snapshot_id, frame, report, message
) -> None:
    with pytest.raises(StorageError, match=message):
        DatasetStore(tmp_path).save(snapshot_id, frame, report)


def test_dataset_store_saves_on_windows_without_hard_links(tmp_path) -> None:
    frame = pd.DataFrame({"answer": pd.Series(["yes", "no"], dtype="string")})
    store = DatasetStore(tmp_path)
    with patch("visuaslide.datasets.os.link", side_effect=PermissionError("hard links disabled")):
        stored = store.save(SNAPSHOT_ID, frame, _valid_report())
    pd.testing.assert_frame_equal(store.load(stored.snapshot_id), frame)
