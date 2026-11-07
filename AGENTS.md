# VisuaSlide agent instructions

VisuaSlide is a Python SDK and CLI for turning survey data from Google Sheets into reproducible analysis and refreshable Google Slides presentations.

## Current state and authority

The local `main` branch contains the 0.2.0 multiselect analysis and paginated reporting implementation. Offline verification passed on 7 November 2026: Ruff lint and format checks, 220 tests passed with 3 opt-in Google sandbox checks skipped, wheel build, and import from the wheel outside the source tree. These commits have not been pushed. Google sandbox and rendered slide acceptance remain **Open**; Phase 6 scheduling remains **Open**. Treat Google integration and scheduling as unverified until their gates pass.

- Read the root `README.md` when present and the files relevant to the task before changing them.
- Check applicable instructions in directories you change. Apply explicitly invoked skills and their workflows within the user's authorized scope.
- Preserve existing user work. Keep changes limited to the requested task.
- Use these status labels consistently: **Accepted** for approved direction, **Proposed** for suggestions awaiting approval, **Open** for unresolved decisions, and **Implemented** only when supported by repository evidence and verification.
- Record material design decisions in repository documentation. Add decision records when significant architecture choices are introduced or superseded; do not create links to files that do not exist.

## Accepted scope and architecture

- The initial product is a local Python library and CLI for one user.
- Each project reads exactly one tab in one Google Sheets source file. Identify it by `spreadsheet_id` and `sheet_id`; resolve the current tab title when building API ranges.
- Keep the survey source read-only in application behavior. Validate write targets and write only to explicitly configured, application-managed outputs.
- Use a separate reporting spreadsheet for aggregate tables and Sheets charts, then embed linked charts in Google Slides. This spreadsheet is an output, not an additional survey source.
- Keep source access, preparation, analysis, storage, reporting, orchestration, and CLI responsibilities separate. The Python API and CLI must call the same underlying behavior.
- Keep the initial runtime local. Add scheduling after manual refresh works reliably.
- Multi-source ingestion, streaming, a web backend, multiple users, AI interpretation, PowerPoint/PDF export, cloud scheduling, and PyPI publication are outside the initial scope.

## Technology direction

Use the accepted stack as the baseline, introducing dependencies only when the task needs them:

- Python, with CPython 3.12 as a baseline to verify before declaring support.
- `uv`, `pyproject.toml`, `uv.lock`, and Hatchling for project management and packaging.
- Google's Python API client, `google-auth`, and `google-auth-oauthlib` for Google integrations.
- Pydantic and TOML for configuration and typed result models.
- pandas for preparation; DuckDB SQL for aggregate analysis; PyArrow/Parquet for typed datasets.
- Sheets embedded charts, Google Slides API, and Google Drive API for reporting and application-managed files.
- Typer for the CLI, standard Python logging and JSON run manifests for diagnostics, pytest and Ruff for checks, GitHub Actions for CI, and Windows Task Scheduler for local scheduling.

Do not implement the same metric independently in pandas and SQL. Pydantic configuration validation does not replace dataset validation. Verify dependency compatibility before pinning versions or claiming platform support.

## Data and statistical rules

- Preserve the raw API values and relevant source metadata before coercion. A raw snapshot is not a complete workbook backup or formula history.
- Require an explicit schema: header mapping, column types, valid categories, missing-value rules, date interpretation, and any filtering or duplicate policy.
- Detect missing or duplicate headers, unknown categories, invalid values, empty inputs, and missing source tabs. Report affected counts without exposing response payloads.
- Do not silently drop duplicate responses, impute missing values, alter identifiers, or choose ambiguous locale/date conversions. Row position is not a durable response identity.
- For the initial version, read the entire configured table on each refresh so additions, edits, and deletions are reflected.
- Record the numerator, denominator, missing-value policy, and applicable grouping for every percentage. Retain calculation precision and round for display.
- Describe sample statistics accurately. Do not choose weights, confidence intervals, hypothesis tests, nonresponse adjustments, or population inference without an approved sampling design and analysis specification.

## Reproducibility and publishing

- Record a run ID, UTC acquisition time, source identity and range, data/configuration hashes, SDK version, and template version.
- Distinguish fetching current Google data from replaying a stored snapshot. Derive all charts, tables, and text for a publication from the same analysis result.
- If skipping unchanged publications, account for data, configuration, code, and template changes.
- Prevent overlapping refreshes for the same project. Repeated execution must not create duplicate slides, charts, or files.
- Use bounded retries for transient errors. Reconcile uncertain creation results before retrying operations that could create duplicates.
- Sheets, Slides, and Drive updates do not form a single transaction. Persist partial failures and never report a partially published run as successful.
- Separate templates from generated presentations. Persist object mappings for subsequent refreshes; do not locate content by searching for its previous displayed value.
- Define SDK-managed and user-edited regions. Report missing managed elements and document which edits a refresh may replace.
- Keep category order and chart colors stable. Check Vietnamese text, long labels, table overflow, and actual slide layout before declaring reporting work complete.

## Credentials and external access

- Never commit credentials, refresh tokens, real survey responses, private snapshots, or presentations containing real survey data. Use synthetic fixtures and secret references.
- Keep credentials separate from project configuration. Exclude runtime data and credentials from version control when those files are introduced.
- OAuth desktop is the accepted local authentication direction. Exact scopes, consent configuration, credential lifecycle, and unattended operation remain to be verified with a Google sandbox.
- The one-tab scope is an application rule, not a claim that OAuth grants access to only that tab. A file ID alone does not establish API permission.
- Do not change sharing permissions, publish data publicly, or contact external services beyond the task's authorized scope.
- Keep logs and errors free of response contents and credentials. Use separate synthetic Google files for live integration checks.

## Verification and delivery

- The verified local checks are `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest tests`, and `uv build --wheel`. Live Google checks remain opt-in and require a separate sandbox.
- For documentation work, check Markdown structure, terminology, status claims, relative links, and the Git diff.
- For implementation, test statistical results against independently calculated small fixtures. Cover data validation, source edits/deletions, repeated refreshes, write-target protection, and partial publishing failures as relevant.
- CI should use synthetic fixtures and mocked Google boundaries. Live integration checks must be explicitly configured against sandbox files; keep them separate from default checks.
- Verify packaging and imports from the built wheel when packaging exists. Verify rendered layout when slide generation exists.
- Follow the applicable commit workflow. Use the branch, push destination, and verification boundaries authorized for the task. Stage explicit paths, review staged changes, and preserve unrelated work.
- Report changed behavior or documentation, checks actually run, commit/push status when applicable, and unresolved limitations. Do not label planned features or unverified checks as complete.
