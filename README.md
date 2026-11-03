# VisuaSlide

**Survey data to reproducible analysis and refreshable presentations.**

VisuaSlide is a planned Python SDK and CLI that connects one survey tab in Google Sheets to a repeatable analysis and Google Slides reporting workflow. It brings data engineering, data analysis, and presentation generation into a project that can be run manually and, later, on a local schedule.

## Project status

**Foundation documentation only.** The technical direction has been accepted, but the SDK, CLI, Google integrations, analysis pipeline, templates, packaging, and CI are not implemented yet. This repository currently provides project guidance and the overview below; it does not provide installation or execution commands.

Documentation uses four status labels:

| Status | Meaning |
| --- | --- |
| **Accepted** | Approved direction for implementation; not evidence that a feature works yet. |
| **Proposed** | A suggestion awaiting approval. |
| **Open** | A decision or assumption that still needs resolution or verification. |
| **Implemented** | Behavior supported by code and verification in this repository. |

## Initial scope — Accepted

- One user, running a Python library or CLI on a local machine.
- Exactly one input tab in one Google Sheets file, selected by spreadsheet ID and sheet ID.
- Read-only handling of the survey source by the application.
- Configured validation, preparation, and descriptive analysis.
- Versioned local snapshots and run records for reproducibility.
- A separate reporting spreadsheet containing aggregate tables and charts.
- A Google Slides presentation containing linked charts, result tables, and data-driven text.
- Manual refresh first; local scheduling after the workflow is reliable.

The reporting spreadsheet is an output. It does not expand ingestion to a second survey source.

Multi-source ingestion, joins across tabs, streaming, a web backend, multiple users, AI-generated interpretation, PowerPoint/PDF export, cloud scheduling, and PyPI publication are outside the initial scope.

## Intended workflow — Accepted

```text
One Google Sheets survey tab
    |
    v
Raw snapshot: API values and source metadata
    |
    v
Validate and prepare with pandas
    |
    v
Clean dataset stored as Parquet
    |
    v
Aggregate analysis with DuckDB SQL
    |
    v
One analysis result: metrics, tables, and reporting content
    |
    v
Reporting spreadsheet: aggregate tables and Sheets charts
    |
    v
Google Slides: linked charts, tables, and text
```

Google Slides supports embedding linked Sheets charts and refreshing them through its API. The chart must first exist in a spreadsheet, which is why this design includes a reporting workbook. [Google Slides chart guide](https://developers.google.com/workspace/slides/api/guides/add-chart)

Keep source access, preparation, analysis, storage, reporting, and orchestration separate. The Python API and CLI will use the same underlying pipeline; the SDK itself will not be a continuously running service.

## Technology direction — Accepted

These are selected technologies for implementation, not installed or verified repository dependencies.

| Responsibility | Technology | Intended use |
| --- | --- | --- |
| Runtime | Python; CPython 3.12 baseline to verify | Run the local SDK and CLI. |
| Project management | uv, `pyproject.toml`, `uv.lock` | Manage dependencies and reproduce development environments. |
| Packaging | Hatchling | Build Python distributions. |
| Google integration | `google-api-python-client` | Call Sheets, Slides, and Drive APIs. |
| Authentication | `google-auth`, `google-auth-oauthlib` | Support desktop OAuth and credential refresh. |
| Configuration and result models | Pydantic, TOML | Validate project configuration and typed outputs. |
| Preparation | pandas | Normalize columns, types, and configured response labels. |
| Dataset storage | Parquet through PyArrow | Store clean data and aggregate datasets with types. |
| Analysis | DuckDB SQL | Define and calculate aggregate results. |
| Charts | Google Sheets embedded charts | Visualize aggregate tables for linked Slides charts. |
| Presentations | Google Slides API | Update managed text, tables, and charts. |
| File and template operations | Google Drive API | Manage application-created files and authorized template copies. |
| CLI | Typer | Expose pipeline operations from the command line. |
| Diagnostics | Python logging, JSON run manifests | Record progress, provenance, and failures. |
| Verification | pytest, Ruff | Check behavior, lint, and formatting. |
| CI | GitHub Actions | Run checks against synthetic data and mocked Google boundaries. |
| Local scheduling | Windows Task Scheduler | Invoke the CLI after manual refresh is established. |

pandas owns preparation, while DuckDB owns the defined aggregate calculations. Pydantic validates configuration and result models; dataset-level validation requires explicit rules. Dependency versions and supported platforms remain to be verified when tooling is introduced.

## Input data and analysis

The intended input is a rectangular table with one header row, one survey response per subsequent row, and one variable per column. The configured region should not contain merged cells or embedded section headings.

A project configuration will specify source identity and range, header mappings, column types, valid categories, missing-value rules, date/locale interpretation, and any filtering or duplicate policy. Configuration examples and executable interfaces will be added with implementation.

Initial descriptive analysis covers:

- Response counts, validation outcomes, and missing values by variable.
- Frequencies and percentages for single-choice categorical variables.
- Valid observation counts, mean, median, minimum, maximum, and standard deviation for configured numeric variables, with calculation conventions documented.
- Configured cross-tabulations with an explicit percentage basis.

Every percentage must retain its numerator, denominator, and missing-value policy. Filtering and duplicate handling must be explicit. Identical answers are not automatically duplicate respondents, and row positions are not stable response identifiers.

**Open:** the actual survey schema, research questions, sampling design, and analysis specification. Weights, confidence intervals, hypothesis tests, nonresponse adjustments, and population inference require those decisions before implementation. Descriptive results about the observed sample must not be presented as population estimates without justification.

## Refresh and reproducibility — Accepted

Each refresh will read the entire configured table and recalculate results so additions, edits, and deletions are reflected. It will preserve the raw response before preparation and record a run ID, UTC acquisition time, source identity/range, data and configuration hashes, SDK version, and template version.

A raw snapshot contains values returned by the API and relevant metadata. It is not a complete workbook backup or formula history. Replaying a stored snapshot and fetching current source data are distinct operations.

Charts, tables, and descriptive text for a publication must come from the same analysis result. If unchanged runs are skipped, the change check must include data, configuration, code, and template identity. Repeated runs must not duplicate managed output objects, and overlapping refreshes for the same project must be prevented.

Publishing spans several Google services and is not a single transaction. A partial failure must remain visible in the run record and support controlled recovery. The pipeline must not report success when only part of the presentation has updated.

## Presentation content and templates — Accepted

The presentation will use a template with defined SDK-managed elements. Initial generation can fill placeholders; subsequent refreshes will use persisted object mappings to update charts, tables, and text. Replacing a placeholder removes that tag, so repeated refreshes cannot depend on finding it again.

Quantitative statements will be derived from calculated metrics. The report author supplies or reviews the research framing, sampling method, interpretation, and conclusions. AI interpretation is a possible later extension.

The intended report structure includes the research question, sampling and collection method, sample composition, data quality, key results, suitable group comparisons, and conclusions with limitations.

Templates and generated presentations must remain separate. Manual edits inside SDK-managed regions may be replaced on refresh; lasting layout changes belong in the template or configuration. Visual verification must cover Vietnamese text, long labels, chart ordering/colors, table overflow, and unresolved placeholders. [Google Slides template guide](https://developers.google.com/workspace/slides/api/guides/merge)

## Google access and data handling

Desktop OAuth is the accepted local authentication direction. Google integration will require a Google Cloud project, enabled Sheets/Slides/Drive APIs, and appropriate consent configuration. Exact scopes, template access, credential storage, and unattended token behavior are **Open** until verified in a sandbox. [Desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app)

The initial approach will evaluate read access to the source and file-scoped write access for application-managed outputs. OAuth does not enforce a one-tab boundary; the SDK must enforce its configured source and write targets. Existing template IDs do not automatically establish file-scoped access. [Google Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

Credentials, tokens, real responses, private snapshots, and generated reports containing real data must stay out of Git. Repository examples and automated checks will use synthetic data. Logs must record diagnostics without response payloads or credentials.

Local scheduling depends on the machine and required environment being available. Credential lifecycle must be verified before promising unattended operation. Cloud execution requires a separate decision about authentication and data storage.

## Implementation roadmap

All milestones below are **Accepted direction** and **not implemented**.

1. **Google integration spike:** read the selected tab, create application-managed output files, generate a chart, embed and refresh it in Slides, and verify authentication and Vietnamese layout.
2. **Project foundation:** introduce packaging, configuration, raw snapshots, schema validation, synthetic fixtures, and CI.
3. **Analysis:** implement clean datasets, documented statistical conventions, aggregate results, and snapshot replay.
4. **Reporting:** implement templates, object mappings, consistent chart/table/text updates, partial-failure handling, and visual verification.
5. **Automation:** stabilize the CLI, prevent overlapping runs, document credential recovery, and add local scheduling.

The first end-to-end acceptance target is: change a response in the source, run one refresh, and see the correct aggregate table, chart, and descriptive text update together. Repeating the refresh must not duplicate slides or charts. Source data must remain unchanged.

## Working in this repository

Read [AGENTS.md](AGENTS.md) before contributing. At this stage there are no established build, test, lint, or installation commands. Add verified instructions when the corresponding tooling exists; planned interfaces should be labeled conceptual until executable.

Documentation changes should be checked for structure, relative links, consistent status labels, and a clean Git diff. Future implementation checks should cover independently calculated statistical fixtures, invalid inputs, source edits/deletions, repeated refreshes, write-target protection, and partial publishing failures. Live Google integration checks should use dedicated synthetic sandbox files and remain separate from default CI.
