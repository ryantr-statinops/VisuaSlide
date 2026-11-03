# Offline workflow

VisuaSlide currently supports a synthetic, local workflow. This path needs no Google account, OAuth file, or network access.

## Environment

Use the pinned Python 3.12 runtime and project lockfile:

```powershell
uv sync --all-groups
```

The example uses only the committed synthetic fixture. Runtime snapshots, Parquet datasets, manifests, and report artifacts are written under `.visuaslide/`, which is ignored by Git.

## Run the Python SDK example

From the repository root:

```powershell
uv run python examples/offline_workflow.py
```

The script loads `examples/survey.example.toml`, reads `tests/fixtures/synthetic_responses.json` through the test-only fixture adapter, saves the snapshot and Parquet dataset, computes configured frequency, numeric summary, and crosstab results, and applies a report to an in-memory fake publisher. It prints the run ID, snapshot ID, row counts, and aggregate tables as JSON.

The fake publisher is process-local. It verifies the same content and update plan interfaces used by a future Google adapter; it does not create Google files or prove that Google OAuth/API calls work.

## Run the CLI in dry-run mode

```powershell
uv run visuaslide refresh `
  --config examples/survey.example.toml `
  --fixture-json tests/fixtures/synthetic_responses.json `
  --dry-run
```

The CLI stores local snapshot, validation, dataset, analysis, and run artifacts. It does not call a publisher. It prints a JSON `RunResult`; a validation failure returns a nonzero exit code and does not persist a clean dataset.

To validate or analyze a saved snapshot, use the `snapshot_id` printed by the previous command:

```powershell
uv run visuaslide validate --config examples/survey.example.toml --snapshot-id <snapshot-id>
uv run visuaslide analyze --config examples/survey.example.toml --snapshot-id <snapshot-id>
uv run visuaslide inspect-run --config examples/survey.example.toml --run-id <run-id>
```

Snapshot validation, analysis, and run inspection operate only on local artifacts and do not read the configured Google source.

## Checks used by the repository

```powershell
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest tests
uv build --wheel
```

Tests use synthetic values and fake adapters. Google sandbox acceptance and visual inspection of a real Slides deck have not been performed.
