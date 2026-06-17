import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import storage
from gcalendar import (
    _format_events,
    get_service,
    NotAuthenticated,
    list_events,
    get_today_events,
    _fetch_events,
    _save_token,
    _load_credentials,
    auth_flow,
)


class TestFormatEvents:
    def test_format_single_event(self):
        events = [{
            "summary": "Team meeting",
            "start": {"dateTime": "2025-01-01T10:00:00Z"},
            "end": {"dateTime": "2025-01-01T11:00:00Z"},
            "location": "Room A",
            "description": "Discuss project",
        }]
        result = _format_events(events)
        assert len(result) == 1
        assert result[0]["summary"] == "Team meeting"
        assert result[0]["start"] == "2025-01-01T10:00:00Z"
        assert result[0]["end"] == "2025-01-01T11:00:00Z"
        assert result[0]["location"] == "Room A"
        assert result[0]["description"] == "Discuss project"

    def test_format_all_day_event(self):
        events = [{
            "summary": "Holiday",
            "start": {"date": "2025-01-01"},
            "end": {"date": "2025-01-02"},
        }]
        result = _format_events(events)
        assert result[0]["start"] == "2025-01-01"
        assert result[0]["end"] == "2025-01-02"
        assert result[0]["location"] is None
        assert result[0]["description"] is None

    def test_format_missing_fields(self):
        events = [{}]
        result = _format_events(events)
        assert result[0]["summary"] == "No title"
        assert result[0]["start"] is None
        assert result[0]["end"] is None
        assert result[0]["location"] is None
        assert result[0]["description"] is None

    def test_format_empty_list(self):
        assert _format_events([]) == []


def test_not_authenticated_stores_url():
    exc = NotAuthenticated("http://auth.url")
    assert exc.auth_url == "http://auth.url"
    assert "http://auth.url" in str(exc)


class TestGetService:
    @pytest.mark.asyncio
    async def test_not_auth_when_no_creds(self):
        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
        }):
            with patch("storage.get_calendar_token", new_callable=AsyncMock, return_value=None):
                with pytest.raises(NotAuthenticated):
                    await get_service("testuser")

    @pytest.mark.asyncio
    async def test_not_auth_when_no_google_env(self):
        with patch.dict("os.environ", {
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
        }):
            with patch("storage.get_calendar_token", new_callable=AsyncMock, return_value=None):
                with pytest.raises(NotAuthenticated) as exc_info:
                    await get_service("testuser")
                assert "GOOGLE_CLIENT_ID" in exc_info.value.auth_url

    @pytest.mark.asyncio
    async def test_get_service_returns_service_when_creds_exist(self, storage_token_mock):
        mock_service = MagicMock()
        with patch("gcalendar.build", return_value=mock_service):
            result = await get_service("testuser")
            assert result is mock_service


class TestSaveToken:
    @pytest.mark.asyncio
    async def test_save_token_saves_to_db(self, storage_token_mock):
        mock_creds = MagicMock()
        mock_creds.token = "test-token"
        mock_creds.refresh_token = "refresh"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "test-id"
        mock_creds.client_secret = "test-secret"
        mock_creds.scopes = ["read"]
        mock_creds.expiry = None

        await _save_token("testuser", mock_creds)
        token_data = await storage.get_calendar_token("testuser")
        assert token_data["token"] == "test-token"


class TestFetchEvents:
    def test_fetch_events_returns_formatted(self, mock_google_service):
        mock_google_service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Test",
                    "start": {"dateTime": "2025-01-01T10:00:00Z"},
                    "end": {"dateTime": "2025-01-01T11:00:00Z"},
                }
            ]
        }
        events = _fetch_events(
            mock_google_service,
            time_min="2025-01-01T00:00:00+00:00",
            time_max="2025-01-08T00:00:00+00:00"
        )
        assert len(events) == 1
        assert events[0]["summary"] == "Test"

    def test_fetch_events_empty(self, mock_google_service):
        mock_google_service.events().list().execute.return_value = {}
        events = _fetch_events(
            mock_google_service,
            time_min="2025-01-01T00:00:00+00:00",
            time_max="2025-01-08T00:00:00+00:00"
        )
        assert events == []


class TestAuthFlow:
    @pytest.mark.asyncio
    async def test_auth_flow_returns_service(self, storage_token_mock):
        mock_service = MagicMock()
        mock_flow = MagicMock()
        mock_flow.credentials.token = "token"
        mock_flow.credentials.refresh_token = "refresh"
        mock_flow.credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_flow.credentials.client_id = "test-id"
        mock_flow.credentials.client_secret = "test-secret"
        mock_flow.credentials.scopes = ["read"]
        mock_flow.credentials.expiry = None

        with patch("gcalendar._build_flow", return_value=mock_flow):
            with patch("gcalendar.build", return_value=mock_service):
                result = await auth_flow("testuser", "mock_auth_response")
                assert result is mock_service

    @pytest.mark.asyncio
    async def test_auth_flow_saves_token(self, storage_token_mock):
        mock_service = MagicMock()
        mock_flow = MagicMock()
        mock_flow.credentials.token = "token"
        mock_flow.credentials.refresh_token = "refresh"
        mock_flow.credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_flow.credentials.client_id = "test-id"
        mock_flow.credentials.client_secret = "test-secret"
        mock_flow.credentials.scopes = ["read"]
        mock_flow.credentials.expiry = None

        with patch("gcalendar._build_flow", return_value=mock_flow):
            with patch("gcalendar.build", return_value=mock_service):
                await auth_flow("testuser", "mock_auth_response")

        token_data = await storage.get_calendar_token("testuser")
        assert token_data["token"] == "token"


class TestLoadCredentials:
    @pytest.mark.asyncio
    async def test_load_credentials_returns_none_when_no_token(self, storage_token_mock):
        creds = await _load_credentials("nonexistent")
        assert creds is None

    @pytest.mark.asyncio
    async def test_load_credentials_returns_creds_when_token_exists(self, storage_token_mock):
        with patch("gcalendar.Credentials") as MockCreds:
            mock_creds = MagicMock()
            mock_creds.valid = True
            MockCreds.return_value = mock_creds
            creds = await _load_credentials("testuser")
            assert creds is mock_creds

    @pytest.mark.asyncio
    async def test_load_credentials_refreshes_invalid_token(self, storage_token_mock):
        with patch("gcalendar.Credentials") as MockCreds:
            mock_creds = MagicMock()
            mock_creds.valid = False
            mock_creds.refresh_token = "refresh"
            MockCreds.return_value = mock_creds
            with patch("gcalendar.Request"):
                with patch("gcalendar._save_token", new_callable=AsyncMock) as mock_save:
                    creds = await _load_credentials("testuser")
                    assert creds is mock_creds
                    mock_creds.refresh.assert_called_once()
                    mock_save.assert_called_once()


class TestEventsUseUTC:
    def test_list_events_uses_utc_time(self, mock_google_service):
        mock_google_service.events().list().execute.return_value = {"items": []}

        list_events(mock_google_service, days=7)
        call_args = mock_google_service.events().list.call_args
        time_min = call_args.kwargs["timeMin"]
        assert time_min.endswith("+00:00")

    def test_get_today_events_uses_utc_time(self, mock_google_service):
        mock_google_service.events().list().execute.return_value = {"items": []}

        get_today_events(mock_google_service)
        call_args = mock_google_service.events().list.call_args
        time_min = call_args.kwargs["timeMin"]
        assert time_min.endswith("+00:00")
