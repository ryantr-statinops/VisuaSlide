# Google sandbox setup and run recovery

**Status: Open for live acceptance.** The Google adapters and opt-in tests exist, but a real OAuth sandbox, source edits, and rendered slides still need verification. Use synthetic responses only until that gate passes.

## Prepare a private sandbox

1. Create a Google Cloud project and enable the [Sheets, Slides, and Drive APIs](https://developers.google.com/workspace/guides/enable-apis).
2. Configure the OAuth consent screen and create a **Desktop app** OAuth client. Add the account you will use as a test user when the consent screen is in testing mode. Download the client JSON to a private local path. Follow [Google's desktop OAuth guide](https://developers.google.com/identity/protocols/oauth2/native-app); never commit or paste the JSON or token.
3. Create a separate Google Sheets file containing only synthetic responses. Use one tab with the exact headers and value formats in `examples/survey.example.toml`. Record its spreadsheet ID (from the URL) and its numeric sheet ID (`gid` in the tab URL). The application resolves the current tab title from that ID.
4. Copy the example TOML to a Git-ignored personal file and edit `source.spreadsheet_id`, `source.sheet_id`, the schema, and report text to match that synthetic tab. Give each developer a distinct `project_dir` inside `.visuaslide/` so tokens, snapshots, run records, and managed output IDs cannot overlap. Paths in `project_dir` are resolved relative to the TOML file.

```powershell
Copy-Item examples/survey.example.toml examples/survey.sandbox.local.toml
# Edit the copied TOML. For example, project_dir = "../.visuaslide/sandbox-yourname".
uv sync --locked --group dev
uv run --locked visuaslide auth --config examples/survey.sandbox.local.toml --client-secret C:\private\client_secret.json
```

`auth` is the only command that deliberately opens a browser. It saves the OAuth token in `<project_dir>/oauth/token.json`. The current code requests `spreadsheets.readonly` for the source and `drive.file` for application-managed output files. These scopes are Google account permissions, not a one-tab permission boundary. Do not add broader scopes or change file sharing to bypass an access error. See [Google's scope reference](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## First publication

Run these commands from the repository root, using the same personal TOML throughout:

```powershell
uv run --locked visuaslide bootstrap-outputs --config examples/survey.sandbox.local.toml
uv run --locked visuaslide refresh --config examples/survey.sandbox.local.toml --dry-run
uv run --locked visuaslide refresh --config examples/survey.sandbox.local.toml
uv run --locked visuaslide review-layout --config examples/survey.sandbox.local.toml
```

`bootstrap-outputs` creates or reuses a reporting spreadsheet, a Slides template, and a separate presentation. Their IDs and managed object mapping are kept in the ignored `<project_dir>/google_outputs.json`; do not delete that registry during recovery. The reporting workbook is an output, never the survey source. `--dry-run` reads and validates the current source and stores local results without publishing. A normal refresh reads the whole configured table and publishes aggregate tables, linked charts, text, and tables. Review every downloaded slide thumbnail as described in [the layout checklist](google-layout-review.md).

The optional `[output]` IDs in TOML must match the local managed registry. Leave them unset for initial bootstrap. The SDK rejects a source file ID or an unregistered file ID as an output target.

## Inspect and recover a run

Every refresh writes a run manifest and, after successful validation, an analysis result under `project_dir`. Save the `run_id` printed by the CLI. A failed validation preserves the raw snapshot and validation report but does not publish. A partial Google publish is marked failed; Sheets and Slides are not one transaction.

```powershell
uv run --locked visuaslide inspect-run --config examples/survey.sandbox.local.toml --run-id <run-id>
uv run --locked visuaslide resume --config examples/survey.sandbox.local.toml --run-id <run-id>
```

`resume` uses that run's saved analysis and completed checkpoints; it does not read the source again. Keep the same TOML, project directory, and managed output registry. If `resume` reports a config mismatch or missing managed object, inspect the files and mapping before changing anything. Fix the cause, then resume the same run where safe. Starting a new refresh takes a new source snapshot and may reflect later edits.

To replay a snapshot without Google access, use its printed `snapshot_id`:

```powershell
uv run --locked visuaslide validate --config examples/survey.sandbox.local.toml --snapshot-id <snapshot-id>
uv run --locked visuaslide analyze --config examples/survey.sandbox.local.toml --snapshot-id <snapshot-id>
```

If a token is absent, expired beyond refresh, or missing a required scope, run `auth` interactively again. An external OAuth app in Google's **Testing** state may issue a refresh token that expires after seven days; see [Google's OAuth guidance](https://developers.google.com/identity/protocols/oauth2#expiration). Neither `refresh` nor `resume` starts browser consent.

## Live acceptance record

After OAuth works, run `uv run --locked pytest tests/sandbox -q` with `VISUASLIDE_SANDBOX_CONFIG` set to the private TOML path. These tests are skipped without that environment variable. With the test source, perform separate add, edit, and delete scenarios; after each refresh, compare source rows, aggregate workbook, linked chart, slide text/table, and rendered thumbnails. Record results privately without committing responses or screenshots. A successful mocked or offline test does not certify this live gate.
