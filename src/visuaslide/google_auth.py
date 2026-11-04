"""Local Google credentials; authorization is an explicit CLI operation."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from visuaslide.exceptions import ConfigurationError

REQUIRED_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.file",
)


class GoogleCredentialStore:
    """Load and refresh a token without starting an interactive OAuth flow."""

    def __init__(self, project_dir: Path) -> None:
        self.path = Path(project_dir).resolve() / "oauth" / "token.json"

    def load(self) -> Credentials:
        try:
            credentials = Credentials.from_authorized_user_file(str(self.path))
        except (OSError, ValueError, TypeError) as exc:
            raise ConfigurationError(
                "Google token is unavailable or invalid; run visuaslide auth."
            ) from exc
        if not credentials.has_scopes(REQUIRED_SCOPES):
            raise ConfigurationError(
                "Google token lacks required scopes; run visuaslide auth again."
            )
        if not credentials.valid:
            if not credentials.refresh_token:
                raise ConfigurationError("Google token cannot refresh; run visuaslide auth again.")
            try:
                credentials.refresh(Request())
            except Exception as exc:
                raise ConfigurationError(
                    "Google token refresh failed; run visuaslide auth again."
                ) from exc
            self.save(credentials)
        return credentials

    def save(self, credentials: Credentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(credentials.to_json())
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise ConfigurationError("Could not save the local Google token.") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def authorize_desktop(client_secret: Path, project_dir: Path) -> Path:
    """Run the explicit desktop consent flow and persist its local token."""
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), list(REQUIRED_SCOPES))
        credentials = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
    except Exception as exc:
        raise ConfigurationError("Google desktop authorization failed.") from exc
    if not credentials.has_scopes(REQUIRED_SCOPES):
        raise ConfigurationError("Google authorization did not grant the required scopes.")
    store = GoogleCredentialStore(project_dir)
    store.save(credentials)
    return store.path
