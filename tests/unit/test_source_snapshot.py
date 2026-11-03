from datetime import UTC, datetime

from visuaslide.config import SourceConfig
from visuaslide.snapshots import SourceSnapshot
from visuaslide.testing import fixture_source


def test_snapshot_capture_preserves_source_rows_and_metadata() -> None:
    source = SourceConfig(spreadsheet_id="synthetic", sheet_id=8, column_range="A:F")
    acquired_at = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)

    snapshot = SourceSnapshot.capture(
        source,
        headers=("Response ID", "Score"),
        rows=(("r001", 8), ("r002", None)),
        acquired_at=acquired_at,
        locale="en_US",
        timezone="Asia/Ho_Chi_Minh",
    )

    assert snapshot.source_first_row == 2
    assert snapshot.metadata.sheet_id == 8
    assert snapshot.metadata.locale == "en_US"
    assert snapshot.rows[1][1] is None


def test_fixture_source_only_serves_its_configured_synthetic_tab() -> None:
    source = SourceConfig(spreadsheet_id="synthetic", sheet_id=8, column_range="A:F")
    snapshot = SourceSnapshot.capture(
        source,
        headers=("Response ID",),
        rows=(("r001",),),
        acquired_at=datetime(2026, 11, 3, tzinfo=UTC),
    )

    assert fixture_source(snapshot).read(source) == snapshot

    try:
        fixture_source(snapshot).read(
            SourceConfig(spreadsheet_id="other", sheet_id=8, column_range="A:F")
        )
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("fixture reader accepted a different source")
