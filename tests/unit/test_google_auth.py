from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from visuaslide.cli import app
from visuaslide.exceptions import ConfigurationError
from visuaslide.google_auth import REQUIRED_SCOPES, GoogleCredentialStore, authorize_desktop


def test_google_token_load_refreshes_and_persists_only_with_required_scopes(tmp_path) -> None:
    credentials = Mock(valid=False, refresh_token="private-refresh-token")
    credentials.has_scopes.return_value = True
    credentials.to_json.return_value = '{"refresh_token":"private-refresh-token"}'
    store = GoogleCredentialStore(tmp_path)
    with patch(
        "visuaslide.google_auth.Credentials.from_authorized_user_file", return_value=credentials
    ):
        assert store.load() is credentials
    credentials.has_scopes.assert_called_once_with(REQUIRED_SCOPES)
    credentials.refresh.assert_called_once()
    assert store.path.read_text("utf-8") == credentials.to_json.return_value


def test_google_token_errors_do_not_expose_secret_values(tmp_path) -> None:
    store = GoogleCredentialStore(tmp_path)
    with patch(
        "visuaslide.google_auth.Credentials.from_authorized_user_file",
        side_effect=ValueError("private-token-value"),
    ):
        with pytest.raises(ConfigurationError) as error:
            store.load()
    assert "private-token-value" not in str(error.value)


def test_google_token_rejects_missing_scope_before_refresh(tmp_path) -> None:
    credentials = Mock(valid=False, refresh_token="private-refresh-token")
    credentials.has_scopes.return_value = False
    store = GoogleCredentialStore(tmp_path)
    with patch(
        "visuaslide.google_auth.Credentials.from_authorized_user_file", return_value=credentials
    ):
        with pytest.raises(ConfigurationError, match="lacks required scopes"):
            store.load()
    credentials.refresh.assert_not_called()


def test_desktop_authorization_is_explicit_and_saves_token(tmp_path) -> None:
    credentials = Mock()
    credentials.has_scopes.return_value = True
    credentials.to_json.return_value = '{"token":"private"}'
    flow = Mock()
    flow.run_local_server.return_value = credentials
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text("{}", encoding="utf-8")

    with patch(
        "visuaslide.google_auth.InstalledAppFlow.from_client_secrets_file", return_value=flow
    ) as create_flow:
        token_path = authorize_desktop(client_secret, tmp_path)

    create_flow.assert_called_once_with(str(client_secret), list(REQUIRED_SCOPES))
    flow.run_local_server.assert_called_once_with(host="127.0.0.1", port=0, open_browser=True)
    assert token_path.read_text("utf-8") == credentials.to_json.return_value


def test_cli_auth_calls_desktop_flow_only_for_auth_command(tmp_path) -> None:
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        (Path(__file__).parents[2] / "examples/survey.example.toml").read_text("utf-8"),
        encoding="utf-8",
    )
    secret = tmp_path / "client_secret.json"
    secret.write_text("{}", encoding="utf-8")
    with patch("visuaslide.cli.authorize_desktop", return_value=tmp_path / "token.json") as auth:
        result = CliRunner().invoke(
            app, ["auth", "--config", str(config_path), "--client-secret", str(secret)]
        )
    assert result.exit_code == 0, result.output
    assert '"status": "authorized"' in result.output
    auth.assert_called_once()
