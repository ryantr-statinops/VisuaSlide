"""Local source-to-analysis orchestration for one configured survey project."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from visuaslide.analysis import calculate_crosstab, calculate_frequency, calculate_numeric_summary
from visuaslide.config import (
    CrosstabAnalysis,
    FrequencyAnalysis,
    NumericSummaryAnalysis,
    ProjectConfig,
    VariableKind,
)
from visuaslide.datasets import DatasetStore
from visuaslide.exceptions import StorageError, VisuaSlideError
from visuaslide.models import (
    AnalysisResult,
    RunResult,
    RunStatus,
    ValidationIssue,
    ValidationReport,
)
from visuaslide.preparation import (
    PreparedColumn,
    prepare_categorical_column,
    prepare_datetime_column,
    prepare_numeric_column,
)
from visuaslide.runs import RunManifest, RunStore
from visuaslide.snapshots import SourceReader, SourceSnapshot, utc_now
from visuaslide.storage import SnapshotStore
from visuaslide.validation import normalize_trailing_cells, validate_snapshot_structure


class SurveyRunner:
    """Acquire, snapshot, validate, prepare, and analyze without publishing."""

    def __init__(self, config: ProjectConfig, source: SourceReader) -> None:
        self.config = config
        self.source = source
        self.snapshots = SnapshotStore(config.project_dir)
        self.datasets = DatasetStore(config.project_dir / "datasets")
        self.runs = RunStore(config.project_dir)

    def refresh(self) -> RunResult:
        """Read a complete source snapshot and produce a local analysis run."""
        manifest = self.runs.create(self.config)
        try:
            manifest = self._update(manifest, stage="acquiring")
            snapshot = self.source.read(self.config.source)
            stored = self.snapshots.save(snapshot)
            manifest = self._update(
                manifest,
                stage="snapshot_saved",
                snapshot_id=stored.snapshot_id,
                completed_step="snapshot",
            )

            manifest = self._update(manifest, stage="validating")
            frame, report = prepare_snapshot(snapshot, self.config, stored.snapshot_id)
            _write_json(
                Path(self.config.project_dir).resolve()
                / "reports"
                / f"{manifest.run_id}.validation.json",
                report.model_dump(mode="json"),
            )
            if not report.is_valid:
                manifest = self._update(
                    manifest,
                    status=RunStatus.VALIDATION_FAILED,
                    stage="validation_failed",
                    error_code="data_validation_failed",
                    completed_step="validation",
                )
                return _run_result(manifest)

            manifest = self._update(
                manifest, stage="preparing_dataset", completed_step="validation"
            )
            self.datasets.save(stored.snapshot_id, frame, report)
            manifest = self._update(manifest, stage="dataset_saved", completed_step="dataset")

            manifest = self._update(manifest, stage="analyzing")
            analysis = analyze_frame(
                frame,
                self.config,
                run_id=manifest.run_id,
                snapshot_id=stored.snapshot_id,
                input_rows=report.input_rows,
                accepted_rows=report.accepted_rows,
            )
            _write_json(
                Path(self.config.project_dir).resolve() / "analyses" / f"{manifest.run_id}.json",
                analysis.model_dump(mode="json"),
            )
            manifest = self._update(
                manifest,
                status=RunStatus.READY,
                stage="analysis_complete",
                completed_step="analysis",
            )
            return _run_result(manifest, analysis)
        except VisuaSlideError:
            self._update(
                manifest,
                status=RunStatus.FAILED,
                stage="failed",
                error_code="pipeline_failed",
            )
            raise
        except Exception:
            self._update(
                manifest,
                status=RunStatus.FAILED,
                stage="failed",
                error_code="pipeline_failed",
            )
            raise

    def _update(
        self,
        manifest: RunManifest,
        *,
        stage: str,
        status: RunStatus | None = None,
        snapshot_id: str | None = None,
        error_code: str | None = None,
        completed_step: str | None = None,
    ) -> RunManifest:
        completed_steps = manifest.completed_steps
        if completed_step and completed_step not in completed_steps:
            completed_steps += (completed_step,)
        updated = RunManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "stage": stage,
                "status": status or manifest.status,
                "snapshot_id": snapshot_id or manifest.snapshot_id,
                "error_code": error_code,
                "completed_steps": completed_steps,
                "updated_at": utc_now(),
            }
        )
        self.runs.save(updated)
        return updated


def prepare_snapshot(
    snapshot: SourceSnapshot, config: ProjectConfig, snapshot_id: str
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate schema and build a clean dataframe, excluding blank source rows."""
    structure = validate_snapshot_structure(snapshot, config.survey_schema, snapshot_id=snapshot_id)
    prepared: dict[str, tuple[object, ...]] = {}
    issues = list(structure.issues)
    dataset_issues = list(structure.dataset_issues)
    for variable in config.survey_schema.variables:
        if variable.kind == VariableKind.CATEGORICAL:
            column = prepare_categorical_column(snapshot, variable)
        elif variable.kind == VariableKind.NUMERIC:
            column = prepare_numeric_column(snapshot, variable)
        elif variable.kind == VariableKind.DATETIME:
            column = prepare_datetime_column(snapshot, variable)
        else:
            column = _prepare_text_column(snapshot, variable)
        prepared[variable.name] = column.values
        for issue in column.issues:
            if issue.code == "missing_configured_header":
                if issue not in dataset_issues:
                    dataset_issues.append(issue)
            else:
                issues.append(issue)

    row_issues = {issue.source_row for issue in issues if issue.source_row is not None}
    invalid_rows = len(row_issues)
    blank_indices = {index for index, row in enumerate(snapshot.rows) if _is_blank_row(row)}
    accepted_rows = max(len(snapshot.rows) - len(blank_indices) - invalid_rows, 0)
    report = ValidationReport(
        snapshot_id=snapshot_id,
        input_rows=len(snapshot.rows),
        blank_rows=len(blank_indices),
        accepted_rows=accepted_rows,
        invalid_rows=invalid_rows,
        issues=tuple(issues),
        dataset_issues=tuple(dataset_issues),
    )

    if not report.is_valid:
        return pd.DataFrame(
            columns=[variable.name for variable in config.survey_schema.variables]
        ), report

    normalized_rows = normalize_trailing_cells(snapshot)
    kept_indices = [index for index, row in enumerate(normalized_rows) if not _is_blank_row(row)]
    frame = pd.DataFrame(
        {
            variable.name: [prepared[variable.name][index] for index in kept_indices]
            for variable in config.survey_schema.variables
        }
    )
    return frame, report


def analyze_frame(
    frame: pd.DataFrame,
    config: ProjectConfig,
    *,
    run_id: str,
    snapshot_id: str,
    input_rows: int,
    accepted_rows: int,
) -> AnalysisResult:
    """Run configured DuckDB analyses and bind them to their source run."""
    variables = {variable.name: variable for variable in config.survey_schema.variables}
    tables = []
    for specification in config.analysis.specifications:
        if isinstance(specification, FrequencyAnalysis):
            tables.append(
                calculate_frequency(frame, variables[specification.variable], specification)
            )
        elif isinstance(specification, NumericSummaryAnalysis):
            tables.append(
                calculate_numeric_summary(frame, variables[specification.variable], specification)
            )
        elif isinstance(specification, CrosstabAnalysis):
            tables.append(
                calculate_crosstab(
                    frame,
                    variables[specification.row_variable],
                    variables[specification.column_variable],
                    specification,
                )
            )
    return AnalysisResult(
        run_id=run_id,
        snapshot_id=snapshot_id,
        created_at=datetime.now(UTC),
        input_rows=input_rows,
        accepted_rows=accepted_rows,
        tables=tuple(tables),
    )


def _prepare_text_column(snapshot: SourceSnapshot, variable) -> PreparedColumn:
    try:
        column_index = snapshot.headers.index(variable.source_header)
    except ValueError:
        return PreparedColumn(
            variable_name=variable.name,
            values=(),
            issues=(
                ValidationIssue(
                    code="missing_configured_header",
                    message="A configured survey column is missing from the source.",
                    variable=variable.name,
                    source_row=snapshot.metadata.header_row,
                ),
            ),
        )
    values = []
    issues = []
    for offset, row in enumerate(snapshot.rows):
        source_row = snapshot.source_first_row + offset
        value = row[column_index] if column_index < len(row) else None
        if value is None or (
            isinstance(value, str)
            and (value.strip() if variable.trim_whitespace else value) in variable.missing_values
        ):
            normalized = None
            if variable.required and not _is_blank_row(row):
                issues.append(
                    ValidationIssue(
                        code="required_value_missing",
                        message="A required text value is missing.",
                        variable=variable.name,
                        source_row=source_row,
                    )
                )
        elif isinstance(value, str):
            normalized = value.strip() if variable.trim_whitespace else value
        else:
            normalized = None
            issues.append(
                ValidationIssue(
                    code="invalid_text_type",
                    message="A text value must be text or an allowed missing value.",
                    variable=variable.name,
                    source_row=source_row,
                )
            )
        values.append(normalized)
    return PreparedColumn(variable.name, tuple(values), tuple(issues))


def _is_blank_row(row: tuple[object, ...]) -> bool:
    return all(value is None or (isinstance(value, str) and value == "") for value in row)


def _run_result(manifest: RunManifest, analysis: AnalysisResult | None = None) -> RunResult:
    return RunResult(
        run_id=manifest.run_id,
        status=manifest.status,
        stage=manifest.stage,
        updated_at=manifest.updated_at,
        snapshot_id=manifest.snapshot_id,
        error_code=manifest.error_code,
        analysis=analysis,
    )


def _write_json(path: Path, value: object) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    except OSError as exc:
        raise StorageError(f"Could not save run artifact {path.name}: {exc}") from exc
