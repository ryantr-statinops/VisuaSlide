# Local Windows scheduling

**Status: Open for live acceptance.** The `--non-interactive` CLI mode is implemented and locally tested for a missing token. Run manual Google refresh and layout acceptance before enabling a recurring task.

First, install the locked environment and complete interactive OAuth and output bootstrap by following [Google setup](google-setup-and-recovery.md). Run one normal refresh successfully. Keep the personal TOML and its `project_dir` at stable absolute locations; the scheduled account must be able to read the local token and write the runtime directory.

In Windows Task Scheduler, create a task under the same Windows account used for `auth`. Choose the trigger yourself. In **Action → Start a program**, set:

| Field | Value |
| --- | --- |
| Program/script | Absolute path to `VisuaSlide\.venv\Scripts\visuaslide.exe` |
| Add arguments | `refresh --config "D:\absolute\path\to\survey.sandbox.local.toml" --non-interactive` |
| Start in | Absolute path to the VisuaSlide repository root; no quotes |

If VisuaSlide is installed as a Git dependency in another Python repository, use that consumer repository's `.venv\Scripts\visuaslide.exe` and its private TOML instead. Run `uv sync --locked` in that repository before scheduling or after updating the pinned SDK commit. Task Scheduler does not install dependencies for you.

The task must not run `auth`: that command opens a browser. `--non-interactive` checks the stored credential before creating a refresh run and exits with code 2 and an actionable message if the token is missing or unusable. It can refresh an expired access token when a valid refresh token exists; it cannot repair revoked consent. Re-run `auth` manually if needed. A validation or publication failure also gives a nonzero exit code; inspect the local run and use `resume` where appropriate. Ensure the schedule does not overlap itself for one project; the project lock also rejects overlapping refreshes.

Test the action once with **Run** in Task Scheduler, inspect its last result, then compare the run manifest and managed deck. Review thumbnails after a real refresh. Keep task output logs private and do not redirect raw response data into tracked files. This repository provides instructions only; it does not register or enable a scheduled task.
