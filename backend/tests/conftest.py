import pytest
import json
import os
import importlib
from unittest.mock import patch, MagicMock

import storage


@pytest.fixture(autouse=True)
def reset_db_path(tmp_path):
    """Isolate DB path per test to avoid shared mutable state."""
    db_path = tmp_path / "test_conversations.db"
    with patch.object(storage, "DB_PATH", db_path):
        yield db_path


@pytest.fixture(autouse=True)
async def setup_test_db(reset_db_path):
    """Initialize DB and seed default users before each test."""
    await storage.init_db()
    await storage.seed_default_users()
    yield


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    import auth
    auth.reset_rate_limiter()
    yield


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
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
    }))
    tf.chmod(0o600)
    return tf


@pytest.fixture
def mock_credentials():
    """Create mock credentials object for testing."""
    mock = MagicMock()
    mock.token = "test-token"
    mock.refresh_token = "test-refresh"
    mock.token_uri = "https://oauth2.googleapis.com/token"
    mock.client_id = "test-id"
    mock.client_secret = "test-secret"
    mock.scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    mock.valid = True
    return mock


@pytest.fixture
def google_env_setup(tmp_path):
    """Set up Google OAuth env vars for tests that need real flow behavior."""
    with patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/calendar/callback",
    }):
        yield


@pytest.fixture
async def storage_token_mock():
    """Set up Google OAuth env vars and seed a test token in the DB for user 'testuser'."""
    with patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/calendar/callback",
    }):
        await storage.save_calendar_token("testuser", {
            "token": "test-token",
            "refresh_token": "test-refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-id",
            "client_secret": "test-secret",
            "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        })
        yield


@pytest.fixture
def e2e_test_credentials():
    """Return E2E test account credentials from environment.

    These are dedicated test account credentials, not a real user account.
    Used only by integration/E2E tests to verify OAuth + Calendar flow end-to-end.
    """
    account = os.environ.get("E2E_TEST_GOOGLE_ACCOUNT")
    password = os.environ.get("E2E_TEST_GOOGLE_PASSWORD")
    if not account or not password:
        pytest.skip("E2E_TEST_GOOGLE_ACCOUNT/E2E_TEST_GOOGLE_PASSWORD not set")
    return {"account": account, "password": password}


@pytest.fixture
def mock_google_service():
    """Create a mock Google Calendar service."""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {"items": []}
    return service


@pytest.fixture
def app_no_calendar():
    """FastAPI app fixture without Google Calendar credentials (NotAuthenticated path).

    Note: Uses importlib.reload(main) which is fragile — resets all module-level state.
    SESSION_SECRET is set in env to prevent file-based secret creation during tests.
    Consider replacing with a create_app() factory before the test suite grows significantly.
    """
    with patch.dict(os.environ, {
        "QWEN_API_KEY": "test-key",
        "QWEN_API_URL": "https://test.example.com/v1",
        "MODEL_NAME": "test-model",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        "SESSION_SECRET": "test-secret-for-testing",
    }):
        import settings
        importlib.reload(settings)
        import main
        importlib.reload(main)
        yield main.app


@pytest.fixture
def app_with_calendar():
    """FastAPI app fixture with Google Calendar credentials (authenticated path)."""
    with patch.dict(os.environ, {
        "QWEN_API_KEY": "test-key",
        "QWEN_API_URL": "https://test.example.com/v1",
        "MODEL_NAME": "test-model",
        "GOOGLE_CLIENT_ID": "test-client",
        "GOOGLE_CLIENT_SECRET": "test-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/calendar/callback",
        "SESSION_SECRET": "test-secret-for-testing",
    }):
        import settings
        importlib.reload(settings)
        import main
        importlib.reload(main)
        yield main.app
