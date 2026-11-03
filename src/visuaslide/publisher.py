"""Adapter contract and deterministic fake report publisher."""

from __future__ import annotations

from dataclasses import dataclass

from visuaslide.exceptions import PublishingError
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
        self._objects: dict[str, dict[str, object]] = {}
        self._layout: PresentationLayout | None = None

    @property
    def mapping(self) -> ManagedObjectMap:
        return self._mapping

    @property
    def objects(self) -> dict[str, dict[str, object]]:
        return {object_id: payload.copy() for object_id, payload in self._objects.items()}

    @property
    def layout(self) -> PresentationLayout | None:
        return self._layout

    def publish(self, content: PresentationContent) -> FakePublishResult:
        """Validate layout first, then apply content to stable fake objects."""
        layout = build_default_layout(content)
        plan = plan_report_update(content, self._mapping)
        next_objects = {object_id: payload.copy() for object_id, payload in self._objects.items()}

        for operation in plan.operations:
            exists = operation.object_id in next_objects
            if operation.action == "create":
                if exists:
                    raise PublishingError("A new managed object ID already exists in the output.")
                next_objects[operation.object_id] = operation.payload.copy()
            elif operation.action == "update":
                if not exists:
                    raise PublishingError("A mapped managed object is missing from the output.")
                next_objects[operation.object_id] = operation.payload.copy()
            elif not exists:
                raise PublishingError("An unchanged managed object is missing from the output.")

        self._objects = next_objects
        self._mapping = plan.mapping
        self._layout = layout
        return FakePublishResult(
            plan=plan,
            layout=layout,
            managed_object_count=len(self._objects),
        )
