"""Command-line entry point for local VisuaSlide workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from visuaslide import SurveyProject
from visuaslide.exceptions import VisuaSlideError

app = typer.Typer(
    name="visuaslide",
    help="Validate and analyze survey snapshots, then prepare report outputs.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("validate")
def validate_command(
    config: Annotated[Path, typer.Option("--config", exists=True, readable=True)],
    snapshot_id: Annotated[str, typer.Option("--snapshot-id")],
) -> None:
    """Validate a previously stored source snapshot."""
    project = _project(config)
    try:
        report = project.validate(snapshot_id)
    except VisuaSlideError as exc:
        _fail(exc)
    _print_json({**report.model_dump(mode="json"), "is_valid": report.is_valid})
    if not report.is_valid:
        raise typer.Exit(code=1)


@app.command("analyze")
def analyze_command(
    config: Annotated[Path, typer.Option("--config", exists=True, readable=True)],
    snapshot_id: Annotated[str, typer.Option("--snapshot-id")],
) -> None:
    """Analyze a previously stored snapshot without reading Google Sheets."""
    project = _project(config)
    try:
        result = project.analyze(snapshot_id)
    except VisuaSlideError as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


@app.command("inspect-run")
def inspect_run_command(
    config: Annotated[Path, typer.Option("--config", exists=True, readable=True)],
    run_id: Annotated[str, typer.Option("--run-id")],
) -> None:
    """Inspect local status, provenance, aggregate results, and errors."""
    project = _project(config)
    try:
        result = project.inspect_run(run_id)
    except VisuaSlideError as exc:
        _fail(exc)
    _print_json(result.model_dump(mode="json"))


def _project(path: Path) -> SurveyProject:
    try:
        return SurveyProject.from_toml(path)
    except VisuaSlideError as exc:
        _fail(exc)


def _print_json(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _fail(error: VisuaSlideError) -> None:
    message = {"error": type(error).__name__, "message": str(error)}
    typer.echo(json.dumps(message, ensure_ascii=False), err=True)
    raise typer.Exit(code=2)


def main() -> None:
    try:
        app()
    except VisuaSlideError as exc:
        _fail(exc)


if __name__ == "__main__":
    main()
