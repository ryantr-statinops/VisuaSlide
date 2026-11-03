"""Stable Python SDK facade over the local survey workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from visuaslide.config import ProjectConfig, load_config
from visuaslide.exceptions import (
    ConfigurationError,
    DataValidationError,
    PublishingError,
    StorageError,
)
from visuaslide.layouts import build_default_layout
from visuaslide.locking import ProjectLock
from visuaslide.models import AnalysisResult, RunResult, RunStatus, ValidationReport
from visuaslide.pipeline import SurveyRunner
from visuaslide.reporting import PresentationContent
from visuaslide.retry import RetryPolicy, call_with_retries
from visuaslide.runs import RunManifest, RunStore, effective_config_hash
from visuaslide.snapshots import SourceReader
from visuaslide.update_plan import ReportUpdatePlan, plan_report_update


class ReportPublisher(Protocol):
    """Boundary implemented by offline and Google reporting adapters."""

    @property
    def mapping(self):
        """Return the persisted mapping of managed output objects."""

    def publish_step(
        self,
        step: str,
        content: PresentationContent,
        plan: ReportUpdatePlan,
    ) -> None:
        """Apply one workbook, chart, or Slides checkpoint."""


class _UnavailableSource:
    def read(self, source):
        raise ConfigurationError("No source adapter is configured for this project.")


class SurveyProject:
    """Public SDK facade for one TOML-configured survey project."""

    def __init__(
        self,
        config: ProjectConfig,
        *,
        source: SourceReader | None = None,
        publisher: ReportPublisher | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config
        self.source = source or _UnavailableSource()
        self.publisher = publisher
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep = sleep
        self._runner = SurveyRunner(
            config,
            self.source,
            retry_policy=self.retry_policy,
            sleep=sleep,
        )
        self._runs = RunStore(config.project_dir)

    @classmethod
    def from_toml(
        cls,
        path: str | Path,
        *,
        source: SourceReader | None = None,
        publisher: ReportPublisher | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> SurveyProject:
        """Load a validated TOML project and inject local or Google adapters."""
        return cls(
            load_config(path),
            source=source,
            publisher=publisher,
            retry_policy=retry_policy,
            sleep=sleep,
        )

    def validate(self, snapshot_id: str) -> ValidationReport:
        """Validate a locally stored snapshot without source access."""
        return self._runner.validate_snapshot(snapshot_id)

    def analyze(self, snapshot_id: str) -> AnalysisResult:
        """Analyze a locally stored snapshot without source access."""
        result = self._runner.analyze_snapshot(snapshot_id)
        if result.analysis is None:
            raise DataValidationError(
                "Snapshot validation failed; inspect the saved validation report before analysis."
            )
        return result.analysis

    def refresh(self, *, dry_run: bool = False) -> RunResult:
        """Acquire and analyze the source, optionally applying a report publisher."""
        if not dry_run and self.publisher is None:
            raise PublishingError("No report publisher is configured; use dry_run=True offline.")
        if dry_run:
            result = self._runner.refresh()
            if result.status != RunStatus.READY or result.analysis is None:
                return result
            return self._update_run_result(result, stage="dry_run_complete")

        with ProjectLock(self.config.project_dir):
            result = self._runner.refresh(acquire_lock=False)
            if result.status != RunStatus.READY or result.analysis is None:
                return result
            try:
                self._publish_checkpoints(result.run_id, result.analysis)
            except Exception as exc:
                self._update_manifest(
                    result.run_id,
                    status=RunStatus.FAILED,
                    stage="publish_failed",
                    error_code="publish_failed",
                )
                if isinstance(exc, PublishingError):
                    raise
                raise PublishingError("Report publishing failed; inspect local run state.") from exc
        return self._update_run_result(
            result,
            status=RunStatus.COMPLETED,
            stage="published",
            completed_step="publish",
        )

    def inspect_run(self, run_id: str) -> RunResult:
        """Read local run state, analysis, and provenance without contacting adapters."""
        manifest = self._runs.load(run_id)
        analysis_path = Path(self.config.project_dir).resolve() / "analyses" / f"{run_id}.json"
        analysis = (
            AnalysisResult.model_validate_json(analysis_path.read_bytes())
            if analysis_path.is_file()
            else None
        )
        return RunResult(
            run_id=manifest.run_id,
            status=manifest.status,
            stage=manifest.stage,
            updated_at=manifest.updated_at,
            snapshot_id=manifest.snapshot_id,
            error_code=manifest.error_code,
            analysis=analysis,
        )

    def bootstrap_outputs(self):
        """Delegate output creation to an adapter that supports bootstrapping."""
        bootstrap = getattr(self.publisher, "bootstrap_outputs", None)
        if bootstrap is None:
            raise PublishingError("The configured publisher does not support output bootstrap.")
        return bootstrap()

    def resume(self, run_id: str) -> RunResult:
        """Resume publication from the immutable analysis saved for this run."""
        manifest = self._runs.load(run_id)
        if manifest.status == RunStatus.COMPLETED:
            return self.inspect_run(run_id)
        if manifest.status not in {RunStatus.READY, RunStatus.PUBLISHING, RunStatus.FAILED}:
            raise PublishingError("This run is not in a resumable publication state.")
        if manifest.snapshot_id is None:
            raise PublishingError("This run has no stored source snapshot to resume.")
        if manifest.config_hash != effective_config_hash(self.config):
            raise ConfigurationError(
                "Resume requires the effective configuration recorded by this run."
            )
        if self.publisher is None:
            raise PublishingError("No report publisher is configured for run recovery.")

        analysis_path = Path(self.config.project_dir).resolve() / "analyses" / f"{run_id}.json"
        try:
            analysis = AnalysisResult.model_validate_json(analysis_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise StorageError("Stored analysis result is unavailable for run recovery.") from exc
        if analysis.run_id != run_id or analysis.snapshot_id != manifest.snapshot_id:
            raise StorageError("Stored analysis provenance does not match this run.")

        with ProjectLock(self.config.project_dir):
            try:
                self._publish_checkpoints(run_id, analysis)
            except Exception as exc:
                self._update_manifest(
                    run_id,
                    status=RunStatus.FAILED,
                    stage="resume_failed",
                    error_code="resume_failed",
                )
                if isinstance(exc, PublishingError):
                    raise
                raise PublishingError("Run recovery failed; inspect local run state.") from exc
        result = RunResult(
            run_id=run_id,
            status=RunStatus.READY,
            stage="analysis_complete",
            updated_at=analysis.created_at,
            snapshot_id=analysis.snapshot_id,
            analysis=analysis,
        )
        return self._update_run_result(
            result,
            status=RunStatus.COMPLETED,
            stage="published",
            completed_step="publish",
        )

    def _publish_checkpoints(self, run_id: str, analysis: AnalysisResult) -> None:
        from visuaslide.reporting import build_presentation_content

        publish_step = getattr(self.publisher, "publish_step", None)
        if publish_step is None:
            raise PublishingError("The configured publisher does not support checkpoints.")
        content = build_presentation_content(analysis, self.config.report)
        build_default_layout(content)
        plan = plan_report_update(content, self.publisher.mapping)
        manifest = self._update_manifest(
            run_id,
            status=RunStatus.PUBLISHING,
            stage="publishing",
        )
        for step in ("workbook", "charts", "slides"):
            if step in manifest.completed_steps:
                continue
            call_with_retries(
                lambda current_step=step: publish_step(current_step, content, plan),
                policy=self.retry_policy,
                **({"sleep": self.sleep} if self.sleep is not None else {}),
            )
            manifest = self._update_manifest(
                run_id,
                status=RunStatus.PUBLISHING,
                stage=f"{step}_published",
                completed_step=step,
            )

    def _update_run_result(
        self,
        result: RunResult,
        *,
        status: RunStatus | None = None,
        stage: str,
        completed_step: str | None = None,
    ) -> RunResult:
        manifest = self._update_manifest(
            result.run_id,
            status=status or result.status,
            stage=stage,
            completed_step=completed_step,
        )
        return RunResult(
            run_id=manifest.run_id,
            status=manifest.status,
            stage=manifest.stage,
            updated_at=manifest.updated_at,
            snapshot_id=manifest.snapshot_id,
            error_code=manifest.error_code,
            analysis=result.analysis,
        )

    def _update_manifest(
        self,
        run_id: str,
        *,
        status: RunStatus,
        stage: str,
        error_code: str | None = None,
        completed_step: str | None = None,
    ) -> RunManifest:
        manifest = self._runs.load(run_id)
        steps = manifest.completed_steps
        if completed_step and completed_step not in steps:
            steps += (completed_step,)
        updated = RunManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "status": status,
                "stage": stage,
                "error_code": error_code,
                "completed_steps": steps,
                "updated_at": datetime.now(UTC),
            }
        )
        self._runs.save(updated)
        return updated
