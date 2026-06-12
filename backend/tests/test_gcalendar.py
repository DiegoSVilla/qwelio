import pytest
import os
from unittest.mock import patch, MagicMock
from gcalendar import (
    _format_events,
    get_service,
    NotAuthenticated,
    list_events,
    get_today_events,
)


class TestFormatEvents:
    def test_format_single_event(self):
        events = [{
            "summary": "Team meeting",
            "start": {"dateTime": "2025-01-01T10:00:00Z"},
            "end": {"dateTime": "2025-01-01T11:00:00Z"},
            "location": "Room A",
        }]
        result = _format_events(events)
        assert len(result) == 1
        assert result[0]["summary"] == "Team meeting"
        assert result[0]["start"] == "2025-01-01T10:00:00Z"
        assert result[0]["location"] == "Room A"

    def test_format_all_day_event(self):
        events = [{
            "summary": "Holiday",
            "start": {"date": "2025-01-01"},
            "end": {"date": "2025-01-02"},
        }]
        result = _format_events(events)
        assert result[0]["start"] == "2025-01-01"

    def test_format_missing_fields(self):
        events = [{}]
        result = _format_events(events)
        assert result[0]["summary"] == "No title"
        assert result[0]["start"] is None

    def test_format_empty_list(self):
        assert _format_events([]) == []


class TestNotAuthenticated:
    def test_exception_stores_url(self):
        exc = NotAuthenticated("http://auth.url")
        assert exc.auth_url == "http://auth.url"
        assert "http://auth.url" in str(exc)


class TestGetService:
    def test_not_auth_when_no_creds(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(NotAuthenticated):
                get_service()

    def test_not_auth_when_no_google_env(self, tmp_path):
        with patch.dict(os.environ, {
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
        }):
            with pytest.raises(NotAuthenticated) as exc_info:
                get_service()
            assert "GOOGLE_CLIENT_ID" in exc_info.value.auth_url


class TestListEvents:
    def test_list_events_calls_correctly(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {
                    "summary": "Test",
                    "start": {"dateTime": "2025-01-01T10:00:00Z"},
                    "end": {"dateTime": "2025-01-01T11:00:00Z"},
                }
            ]
        }

        events = list_events(mock_service, days=7)
        assert len(events) == 1
        assert events[0]["summary"] == "Test"

    def test_today_events_calls_correctly(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": []
        }
        events = get_today_events(mock_service)
        assert events == []

    def test_events_use_utc_time(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {"items": []}

        list_events(mock_service, days=7)
        call_args = mock_service.events().list.call_args
        time_min = call_args.kwargs["timeMin"]
        assert "+00:00" in time_min or "Z" in time_min or "+00" in time_min
