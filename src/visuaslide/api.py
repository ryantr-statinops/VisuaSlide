"""Stable Python SDK facade over the local survey workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from visuaslide.config import ProjectConfig, load_config
from visuaslide.exceptions import ConfigurationError, DataValidationError, PublishingError
from visuaslide.models import AnalysisResult, RunResult, RunStatus, ValidationReport
from visuaslide.pipeline import SurveyRunner
from visuaslide.reporting import PresentationContent
from visuaslide.retry import RetryPolicy, call_with_retries
from visuaslide.runs import RunManifest, RunStore
from visuaslide.snapshots import SourceReader


class ReportPublisher(Protocol):
    """Boundary implemented by offline and Google reporting adapters."""

    def publish(self, content: PresentationContent):
        """Apply one adapter-neutral presentation content object."""


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
        result = self._runner.refresh()
        if result.status != RunStatus.READY or result.analysis is None:
            return result
        if dry_run:
            return self._update_run_result(result, stage="dry_run_complete")

        from visuaslide.reporting import build_presentation_content

        try:
            content = build_presentation_content(result.analysis, self.config.report)
            call_with_retries(
                lambda: self.publisher.publish(content),
                policy=self.retry_policy,
                **({"sleep": self.sleep} if self.sleep is not None else {}),
            )
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
        """Delegate recovery to an adapter that supports run resumption."""
        resume = getattr(self.publisher, "resume", None)
        if resume is None:
            raise PublishingError("Run resume is not available in the configured publisher.")
        return resume(run_id)

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
