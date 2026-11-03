"""Immutable in-memory representation of one source acquisition."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from pydantic import Field, field_validator

from visuaslide.config import SourceConfig, StrictModel
from visuaslide.models import Scalar


class SourceMetadata(StrictModel):
    """Source identity and value-rendering details attached to a snapshot."""

    spreadsheet_id: str
    sheet_id: int = Field(ge=0)
    column_range: str
    header_row: int = Field(ge=1)
    locale: str | None = None
    timezone: str | None = None
    value_render_option: str


class SourceSnapshot(StrictModel):
    """Raw header and rows returned by one read of the configured tab."""

    metadata: SourceMetadata
    acquired_at: datetime
    headers: tuple[str, ...]
    rows: tuple[tuple[Scalar, ...], ...]
    source_first_row: int = Field(ge=1)

    @field_validator("acquired_at")
    @classmethod
    def normalize_acquisition_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquired_at must include a timezone")
        return value.astimezone(UTC)

    @classmethod
    def capture(
        cls,
        source: SourceConfig,
        *,
        headers: tuple[str, ...],
        rows: tuple[tuple[Scalar, ...], ...],
        acquired_at: datetime,
        value_render_option: str = "UNFORMATTED_VALUE",
        locale: str | None = None,
        timezone: str | None = None,
    ) -> SourceSnapshot:
        """Capture raw values while preserving source row positions."""
        return cls(
            metadata=SourceMetadata(
                spreadsheet_id=source.spreadsheet_id,
                sheet_id=source.sheet_id,
                column_range=source.column_range,
                header_row=source.header_row,
                locale=locale,
                timezone=timezone,
                value_render_option=value_render_option,
            ),
            acquired_at=acquired_at,
            headers=headers,
            rows=rows,
            source_first_row=source.header_row + 1,
        )


class SourceReader(Protocol):
    """Internal boundary for retrieving one source snapshot."""

    def read(self, source: SourceConfig) -> SourceSnapshot:
        """Read the configured source and return raw values with metadata."""


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for a source read."""
    return datetime.now(UTC)
