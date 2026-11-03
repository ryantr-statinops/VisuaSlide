"""Test-only adapters for exercising the single-source pipeline offline."""

from __future__ import annotations

from visuaslide.config import SourceConfig
from visuaslide.snapshots import SourceReader, SourceSnapshot


class FixtureSource:
    """Return a supplied synthetic snapshot through the source boundary."""

    def __init__(self, snapshot: SourceSnapshot) -> None:
        self._snapshot = snapshot

    def read(self, source: SourceConfig) -> SourceSnapshot:
        if self._snapshot.metadata.spreadsheet_id != source.spreadsheet_id:
            raise ValueError("fixture snapshot does not match the configured source")
        if self._snapshot.metadata.sheet_id != source.sheet_id:
            raise ValueError("fixture snapshot does not match the configured sheet ID")
        return self._snapshot


def fixture_source(snapshot: SourceSnapshot) -> SourceReader:
    """Build a fixture reader for tests without adding another product source."""
    return FixtureSource(snapshot)
