# Multiselect configuration and report pagination

**Status — Implemented and verified offline.** Google sandbox and rendered slide acceptance remain **Open**. See [the decision record](decisions/0001-multiselect-and-pagination.md) and the [current project status](../README.md#project-status).

## Configure and replay synthetic data

[The complete example TOML](../examples/multiselect.example.toml) includes thirteen faculties, aliases, a choice containing commas, and a numeric allowed-value set. [The example responses](../examples/multiselect.example.json) are entirely synthetic.

```powershell
uv run --locked visuaslide refresh --config examples/multiselect.example.toml --fixture-json examples/multiselect.example.json --dry-run
```

Use the printed snapshot ID with the existing `validate` and `analyze` commands to replay the stored source. Through Python, `SurveyProject.refresh(dry_run=True)` and `inspect_run(run_id)` return the complete `AnalysisResult`. Consumers should derive their other output formats from that saved result.

## Choice validation and percentages

- Set `kind = "multi_select"`, ordered `categories`, optional `aliases` mapping alternate spellings to canonical choices, and optional `separator` with a comma default. Matching is case-sensitive. Choices and aliases must be trimmed and nonblank.
- Match complete labels from left to right, longest first. A configured label may contain the separator. Whitespace around separators and one trailing separator are accepted. Repeated choices and aliases for the same choice count once per record.
- Missing markers follow the configured schema. An unrecognized answer or fragment fails validation and prevents publication. Diagnostics contain safe issue codes and positions.
- Use `kind = "multi_frequency"` for a multiselect analysis. `non_missing` counts records answering that question. `all_responses` counts all retained records. Every table row includes frequency, numerator, denominator and an unrounded percentage ratio. A zero denominator produces an undefined percentage.
- In the example, IELTS has 2 / 2, PET has 1 / 2, and the other certificates have zero counts. The wanted-information choices have 2 / 3 and 1 / 3. Totals for a multiselect question may exceed 100%.
- Set numeric `allowed_values = [1, 2, 3, 4, 5]` to validate a five-level scale. Omit this option to retain the existing finite numeric behavior.

Prepared multiselect columns use nullable Parquet `list<string>` values. Raw snapshots preserve the original source strings. Aggregation runs in DuckDB.

## Pages, ownership and recovery

Layout version 2 splits frequency tables into pages of ten categories, keeping zero-count categories in configuration order. Thirteen categories produce pages of ten and three. Crosstabs and numeric summaries retain their existing layout limits.

`AnalysisResult.tables` remains complete. `build_presentation_content` exposes page projections with `page_key` and the original `source_analysis_id`. The first page retains its previous object keys. Continuations use `<analysis_id>/page/2`, and their Google object IDs are deterministic.

Each page has a managed reporting tab and managed slide content. Refresh may replace all content on registered analysis pages and reporting tabs. Registry ownership controls removal of obsolete pages and charts. Unregistered user slides are preserved. A missing previously published managed element is an error.

The desired publication is saved under `<project_dir>/publications/<run_id>.json` before Google writes. Keep that artifact, the analysis, manifest and `google_outputs.json` together when resuming. Resume uses the saved projection and does not read the survey source.

Runs created by 0.1 without a saved publication use the legacy layout. A legacy overflow requires a new refresh to use pagination. Existing scalar datasets and one-page IDs remain supported.

For live verification, copy the TOML to an ignored `*.local.toml`, configure a separate synthetic Google Sheet with these headers, and follow [sandbox setup](google-setup-and-recovery.md) and [visual review](google-layout-review.md). Verify every page and its full-question denominator before enabling downstream use.
