"""Adapter contract and deterministic fake report publisher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from visuaslide.exceptions import OutputReconciliationError, PublishingError
from visuaslide.layouts import PresentationLayout, build_default_layout
from visuaslide.reporting import PresentationContent
from visuaslide.update_plan import ManagedObjectMap, ReportUpdatePlan, plan_report_update


@dataclass(frozen=True)
class FakePublishResult:
    """Result of applying a report update plan to the in-memory fake output."""

    plan: ReportUpdatePlan
    layout: PresentationLayout
    managed_object_count: int


class FakeReportPublisher:
    """In-memory workbook/deck stand-in for deterministic offline tests."""

    def __init__(self) -> None:
        self._mapping = ManagedObjectMap()
        self._workbook_objects: dict[str, dict[str, object]] = {}
        self._slide_objects: dict[str, dict[str, object]] = {}
        self._layout: PresentationLayout | None = None

    @property
    def mapping(self) -> ManagedObjectMap:
        return self._mapping

    @property
    def objects(self) -> dict[str, dict[str, object]]:
        return {object_id: payload.copy() for object_id, payload in self._slide_objects.items()}

    @property
    def workbook_objects(self) -> dict[str, dict[str, object]]:
        return {object_id: payload.copy() for object_id, payload in self._workbook_objects.items()}

    @property
    def layout(self) -> PresentationLayout | None:
        return self._layout

    def publish(self, content: PresentationContent) -> FakePublishResult:
        """Validate layout, then apply all fake workbook and slide checkpoints."""
        layout = build_default_layout(content)
        plan = plan_report_update(content, self._mapping)
        for step in ("workbook", "charts", "slides"):
            self.publish_step(step, content, plan)
        self._layout = layout
        return FakePublishResult(
            plan=plan,
            layout=layout,
            managed_object_count=len(self._slide_objects),
        )

    def publish_step(
        self,
        step: Literal["workbook", "charts", "slides"],
        content: PresentationContent,
        plan: ReportUpdatePlan,
    ) -> None:
        """Apply one idempotent local checkpoint to fake workbook/deck state."""
        if step not in {"workbook", "charts", "slides"}:
            raise PublishingError("Unknown report publishing checkpoint.")
        layout = build_default_layout(content)
        if step == "workbook":
            operations = [item for item in plan.operations if item.kind == "table"]
            target = self._workbook_objects
        elif step == "charts":
            operations = [item for item in plan.operations if item.kind == "chart"]
            target = self._workbook_objects
        else:
            operations = list(plan.operations)
            target = self._slide_objects

        next_objects = {object_id: payload.copy() for object_id, payload in target.items()}
        applied_keys = set()
        for operation in operations:
            exists = operation.object_id in next_objects
            if operation.action == "create":
                if exists and next_objects[operation.object_id] != operation.payload:
                    raise OutputReconciliationError(
                        "A managed object ID exists with different content; "
                        "the creation result cannot be reconciled safely."
                    )
                next_objects[operation.object_id] = operation.payload.copy()
            elif operation.action == "update":
                if not exists:
                    if (
                        step == "slides"
                        and operation.kind in {"table", "chart"}
                        and operation.object_id in self._workbook_objects
                    ):
                        next_objects[operation.object_id] = operation.payload.copy()
                    else:
                        raise PublishingError("A mapped managed object is missing from the output.")
                else:
                    next_objects[operation.object_id] = operation.payload.copy()
            elif not exists:
                if (
                    step == "slides"
                    and operation.kind in {"table", "chart"}
                    and operation.object_id in self._workbook_objects
                ):
                    next_objects[operation.object_id] = operation.payload.copy()
                else:
                    raise PublishingError("An unchanged managed object is missing from the output.")
            applied_keys.add(operation.object_key)

        target.clear()
        removed_keys = set()
        for entry in plan.removed:
            if (
                step == "slides"
                or (step == "workbook" and entry.kind == "table")
                or (step == "charts" and entry.kind == "chart")
            ):
                next_objects.pop(entry.object_id, None)
                removed_keys.add(entry.object_key)
        target.update(next_objects)
        entries = {
            entry.object_key: entry
            for entry in self._mapping.entries
            if entry.object_key not in removed_keys
        }
        entries.update(
            {
                entry.object_key: entry
                for entry in plan.mapping.entries
                if entry.object_key in applied_keys
            }
        )
        self._mapping = ManagedObjectMap(entries=tuple(entries.values()))
        if step == "slides":
            self._mapping = plan.mapping
            self._layout = layout
