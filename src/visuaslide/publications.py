"""Immutable desired publication artifacts used by refresh and resume."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from pydantic import Field, model_validator

from visuaslide.config import StrictModel
from visuaslide.exceptions import StorageError
from visuaslide.models import AnalysisResult
from visuaslide.reporting import PresentationContent
from visuaslide.runs import _atomic_write, _sha256
from visuaslide.update_plan import ReportUpdatePlan


class SavedPublication(StrictModel):
    """One versioned content projection bound to an immutable analysis result."""

    analysis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: PresentationContent
    plan: ReportUpdatePlan

    @model_validator(mode="after")
    def check_provenance(self) -> SavedPublication:
        if (
            self.content.run_id != self.plan.run_id
            or self.content.snapshot_id != self.plan.snapshot_id
            or self.content.layout_version != self.plan.layout_version
        ):
            raise ValueError("publication content and plan must have matching provenance")
        return self

    def verify_analysis(self, analysis: AnalysisResult) -> None:
        if (
            self.analysis_hash != _sha256(analysis.model_dump(mode="json"))
            or self.content.run_id != analysis.run_id
            or self.content.snapshot_id != analysis.snapshot_id
        ):
            raise StorageError("Saved publication does not match the run analysis.")


class PublicationStore:
    def __init__(self, project_dir: Path) -> None:
        self.root = Path(project_dir).resolve() / "publications"

    def _path(self, run_id: str) -> Path:
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError("noncanonical UUID")
        except (ValueError, TypeError, AttributeError) as exc:
            raise StorageError("Publication run_id must be a canonical UUID.") from exc
        return self.root / f"{run_id}.json"

    def load(self, run_id: str) -> SavedPublication | None:
        path = self._path(run_id)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StorageError("Could not read the saved publication.") from exc
        try:
            envelope = json.loads(raw)
            if _sha256(envelope["publication"]) != envelope["sha256"]:
                raise ValueError("checksum mismatch")
            saved = SavedPublication.model_validate(envelope["publication"])
            if saved.content.run_id != run_id:
                raise ValueError("run mismatch")
            return saved
        except (ValueError, TypeError, KeyError) as exc:
            raise StorageError(
                "Saved publication is invalid or its integrity check failed."
            ) from exc

    def save(self, saved: SavedPublication) -> None:
        path = self._path(saved.content.run_id)
        payload = saved.model_dump(mode="json")
        envelope = {"publication": payload, "sha256": _sha256(payload)}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            _atomic_write(
                path,
                json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8"),
                replace=False,
            )
        except OSError as exc:
            raise StorageError("Could not persist the immutable publication plan.") from exc
