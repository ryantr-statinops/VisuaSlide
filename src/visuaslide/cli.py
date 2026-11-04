"""Command-line entry point for local VisuaSlide workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from visuaslide import SurveyProject
from visuaslide.config import load_config
from visuaslide.exceptions import ConfigurationError, VisuaSlideError
from visuaslide.google_auth import authorize_desktop
from visuaslide.publisher import FakeReportPublisher
from visuaslide.snapshots import SourceSnapshot, utc_now
from visuaslide.testing import FixtureSource

app = typer.Typer(
    name="visuaslide",
    help="Validate and analyze survey snapshots, then prepare report outputs.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("auth")
def auth_command(
    config: Annotated[Path, typer.Option("--config", exists=True, readable=True)],
    client_secret: Annotated[Path, typer.Option("--client-secret", exists=True, readable=True)],
) -> None:
    """Explicitly open Google desktop consent and save a local token."""
    try:
        project_config = load_config(config)
        token_path = authorize_desktop(client_secret, project_config.project_dir)
    except VisuaSlideError as exc:
        _fail(exc)
    _print_json({"status": "authorized", "token_path": str(token_path)})


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


@app.command("refresh")
def refresh_command(
    config: Annotated[Path, typer.Option("--config", exists=True, readable=True)],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    fixture_json: Annotated[Path | None, typer.Option("--fixture-json", readable=True)] = None,
) -> None:
    """Refresh from an explicit offline fixture and optionally publish to a fake output."""
    if fixture_json is None:
        _fail(
            ConfigurationError(
                "A fixture JSON is required for offline refresh; "
                "Google source support is not available yet."
            )
        )
    try:
        project_config = load_config(config)
        fixture = json.loads(fixture_json.read_text(encoding="utf-8"))
        snapshot = SourceSnapshot.capture(
            project_config.source,
            headers=tuple(fixture["headers"]),
            rows=tuple(tuple(row) for row in fixture["rows"]),
            acquired_at=utc_now(),
        )
        publisher = None if dry_run else FakeReportPublisher()
        project = SurveyProject(
            project_config,
            source=FixtureSource(snapshot),
            publisher=publisher,
        )
        result = project.refresh(dry_run=dry_run)
    except VisuaSlideError as exc:
        _fail(exc)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        _fail(ConfigurationError("The offline fixture JSON could not be loaded."))
    _print_json(result.model_dump(mode="json"))
    if result.status.value in {"validation_failed", "failed"}:
        raise typer.Exit(code=1)


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
