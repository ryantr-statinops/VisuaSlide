from unittest.mock import Mock, patch

import pytest

from visuaslide.exceptions import ConfigurationError
from visuaslide.google_auth import REQUIRED_SCOPES, GoogleCredentialStore


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
