import pytest
import json
import os
from unittest.mock import patch, MagicMock


@pytest.fixture
def token_file(tmp_path):
    """Create a clean token file for tests that need to load credentials."""
    tf = tmp_path / ".calendar_token.json"
    tf.write_text(json.dumps({
        "token": "test-token",
        "refresh_token": "test-refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-id",
        "client_secret": "test-secret",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }))
    tf.chmod(0o600)
    return tf


@pytest.fixture
def mock_credentials(tmp_path):
    """Create mock credentials object for testing."""
    creds_data = {
        "token": "test-token",
        "refresh_token": "test-refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-id",
        "client_secret": "test-secret",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
    }
    mock = MagicMock()
    for k, v in creds_data.items():
        setattr(mock, k, v)
    mock.valid = True
    mock.token = "test-token"
    mock.refresh_token = "test-refresh"
    mock.token_uri = "https://oauth2.googleapis.com/token"
    mock.client_id = "test-id"
    mock.client_secret = "test-secret"
    mock.scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    return mock


@pytest.fixture
def clean_google_env(tmp_path):
    """Set up Google OAuth env vars and TOKEN_PATH for tests that need real flow behavior."""
    token_path = tmp_path / ".calendar_token.json"
    token_path.touch()
    with patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/calendar/callback",
    }):
        with patch("gcalendar.TOKEN_PATH", token_path):
            yield token_path


@pytest.fixture
def mock_google_service():
    """Create a mock Google Calendar service."""
    service = MagicMock()
    service.events = MagicMock()
    service.events.return_value = MagicMock()
    service.events.return_value.list = MagicMock()
    service.events.return_value.list.return_value = MagicMock()
    service.events.return_value.list.return_value.execute = MagicMock()
    return service
