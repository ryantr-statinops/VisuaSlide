# Forking VisuaSlide and using it from another repository

**Status: Implemented and verified for offline development; Open for live Google acceptance.** A GitHub fork contains only commits already pushed to `origin/main`. Consumers should pin a reviewed commit. Google sandbox and rendered-slide acceptance are tracked as a separate follow-up plan; Google API behavior remains unverified until those checks pass.

There are two supported ways to collaborate:

| Goal | What the developer works on |
| --- | --- |
| Contribute changes to VisuaSlide | Fork this repository, clone the fork, run checks, and propose changes back to the upstream repository. |
| Use VisuaSlide in another Python repository | Add this repository as a Git dependency at a reviewed commit, then keep that repository's TOML, runtime, and OAuth files local. |

## 1. Contribute through a fork

Fork `ryantr-statinops/VisuaSlide` on GitHub after the desired commit is on the remote. Clone **your fork** and add the original repository as `upstream` ([GitHub's fork remote guide](https://docs.github.com/en/pull-requests/how-tos/work-with-forks/configuring-a-remote-repository-for-a-fork)):

```powershell
$GitHubUser = "YOUR_GITHUB_USERNAME"
git clone "https://github.com/$GitHubUser/VisuaSlide.git"
Set-Location VisuaSlide
git remote add upstream https://github.com/ryantr-statinops/VisuaSlide.git
git remote -v
git switch -c feature/my-change
uv sync --locked --group dev
uv run --locked python examples/offline_workflow.py
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
uv run --locked pytest tests
```

Use CPython 3.12. The default CI uses synthetic fixtures and mocked Google boundaries; it does not need a Google account. Commit related code and unit tests together. Push the feature branch to your fork and open a pull request to the upstream `main` when ready. Fetch upstream and rebase your feature branch when you intentionally update it; never force-push the upstream repository. Read the root `AGENTS.md` and the repository's `commit-workflow` skill before changing files.

Each developer uses a separate ignored `examples/survey.sandbox.local.toml` and `project_dir`, even if they inspect the same synthetic source file. Do not copy `.visuaslide/`, `oauth/token.json`, `google_outputs.json`, private source responses, or slide screenshots into a fork or pull request. The fork's own CI should stay offline; live checks are opt-in and described in [Google setup](google-setup-and-recovery.md).

## 2. Consume the SDK from another Python repository

VisuaSlide is not published to PyPI. In the **consumer repository**, add a Git dependency pinned to a full commit SHA that is already on the remote. Replace `FULL_COMMIT_SHA` with the reviewed hash:

```powershell
uv add git+https://github.com/ryantr-statinops/VisuaSlide.git --rev FULL_COMMIT_SHA
uv lock
```

`uv add` records the Git source in `pyproject.toml`; commit that file and the consumer repository's `uv.lock`. To use a developer's unpublished fork, replace the URL with that fork's Git URL and pin one of its pushed commits. Update the revision deliberately when moving to a newer SDK commit. See [uv's Git dependency guide](https://docs.astral.sh/uv/concepts/dependencies/#git).

Create a private TOML in the consumer repository by copying `examples/survey.example.toml`. For example, if the file is `config/visuaslide.local.toml`, set `project_dir = "../.visuaslide/my-survey"`; paths are relative to the TOML file. Fill the one source spreadsheet ID, numeric sheet ID, explicit schema, analyses, and report text. Do not put OAuth client JSON or token values in TOML. The consumer repository must ignore its own private files:

```gitignore
.visuaslide/
*.local.toml
.env
.env.*
client_secret*.json
credentials*.json
token.json
*.token.json
*.parquet
```

The project configuration is **TOML**, not `.env`. VisuaSlide does not automatically load `.env`. Environment variables currently serve only the opt-in sandbox test path (`VISUASLIDE_SANDBOX_CONFIG` and its optional expectations). If the consumer uses `.env` for its own settings, its own loader must read it; keep it ignored. OAuth uses a local client JSON supplied to `visuaslide auth` and stores the token under the configured `project_dir`.

From Python in the consumer repository:

```python
from visuaslide import SurveyProject

project = SurveyProject.from_toml("config/visuaslide.local.toml")
run = project.refresh(dry_run=True)
print(run.run_id, run.status)
```

The same installed package exposes the CLI:

```powershell
uv run --locked visuaslide refresh --config config/visuaslide.local.toml --dry-run
```

After the Google sandbox gate passes, follow [Google setup and recovery](google-setup-and-recovery.md) for `auth`, `bootstrap-outputs`, publication, and resume. A non-Python consumer can invoke the CLI with an explicit TOML path and check its process exit code and JSON output; it still needs a Python 3.12 environment containing VisuaSlide.

## Shared source and output boundaries

- Give every developer a distinct local `project_dir`. Its token, snapshots, runs, and output registry belong together. Do not share or recreate the registry casually: it binds managed Google file IDs and object IDs.
- Prefer a separate synthetic Sheets source per developer for live tests. If a team shares one synthetic source, arrange read access outside VisuaSlide and coordinate edits; each developer should still bootstrap separate managed outputs under their own account.
- The application reads only the configured source tab and does not write to it. Output workbook, template, and presentation are created and verified as managed files. An arbitrary existing file ID cannot be adopted as a write target merely by putting it in TOML.
- Use no real survey responses, credentials, private snapshots, or generated decks in Git or CI artifacts. Keep live integration checks outside default CI until the sandbox gate has been completed.
