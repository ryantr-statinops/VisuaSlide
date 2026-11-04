"""Stable identity mapping and deterministic plans for managed report objects."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

from pydantic import Field, model_validator

from visuaslide.config import StrictModel
from visuaslide.reporting import PresentationContent

_OBJECT_NAMESPACE = uuid.UUID("76376a4f-64e1-4f3d-9ec4-ff8a842aa3d8")


def managed_object_id(object_key: str) -> str:
    """Stable Slides object ID for a report element key."""
    return uuid.uuid5(_OBJECT_NAMESPACE, object_key).hex


class ManagedObject(StrictModel):
    """Persisted stable identity for one application-owned presentation element."""

    object_key: str = Field(min_length=1)
    object_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    kind: Literal["title", "text", "table", "chart"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ManagedObjectMap(StrictModel):
    """Identity map stored alongside a managed report presentation."""

    entries: tuple[ManagedObject, ...] = ()

    @model_validator(mode="after")
    def check_unique_identities(self) -> ManagedObjectMap:
        keys = [entry.object_key for entry in self.entries]
        ids = [entry.object_id for entry in self.entries]
        if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
            raise ValueError("managed object keys and IDs must be unique")
        return self


class PlannedObjectUpdate(StrictModel):
    """One adapter-neutral operation for a managed report element."""

    object_key: str
    object_id: str
    kind: Literal["title", "text", "table", "chart"]
    action: Literal["create", "update", "unchanged"]
    payload: dict[str, object]


class ReportUpdatePlan(StrictModel):
    """Complete desired update for one presentation content version."""

    run_id: str
    snapshot_id: str
    operations: tuple[PlannedObjectUpdate, ...]
    mapping: ManagedObjectMap


def plan_report_update(
    content: PresentationContent,
    existing: ManagedObjectMap | None = None,
) -> ReportUpdatePlan:
    """Plan create/update operations while retaining stable object identities."""
    current = existing or ManagedObjectMap()
    existing_by_key = {entry.object_key: entry for entry in current.entries}
    desired = _desired_objects(content)
    next_by_key = dict(existing_by_key)
    operations = []

    for object_key, kind, payload in desired:
        digest = _content_hash(payload)
        prior = existing_by_key.get(object_key)
        object_id = prior.object_id if prior else managed_object_id(object_key)
        action = (
            "create" if prior is None else "unchanged" if prior.content_hash == digest else "update"
        )
        next_by_key[object_key] = ManagedObject(
            object_key=object_key,
            object_id=object_id,
            kind=kind,
            content_hash=digest,
        )
        operations.append(
            PlannedObjectUpdate(
                object_key=object_key,
                object_id=object_id,
                kind=kind,
                action=action,
                payload=payload,
            )
        )

    return ReportUpdatePlan(
        run_id=content.run_id,
        snapshot_id=content.snapshot_id,
        operations=tuple(operations),
        mapping=ManagedObjectMap(entries=tuple(next_by_key.values())),
    )


def _desired_objects(content: PresentationContent) -> list[tuple[str, str, dict[str, object]]]:
    desired: list[tuple[str, str, dict[str, object]]] = [
        ("title:report", "title", {"text": content.title, "locale": content.locale})
    ]
    desired.extend(
        (f"text:{item.object_id}", "text", item.model_dump(mode="json"))
        for item in content.text_blocks
    )
    desired.extend(
        (f"table:{item.source_analysis_id}", "table", item.model_dump(mode="json"))
        for item in content.tables
    )
    desired.extend(
        (f"chart:{item.source_analysis_id}", "chart", item.model_dump(mode="json"))
        for item in content.charts
    )
    return desired


def _content_hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
