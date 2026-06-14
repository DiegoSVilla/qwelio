import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from main import _do_filter, _do_parse_date_range
from gcalendar import NotAuthenticated


@pytest.fixture
async def client(app_no_calendar):
    """Unauthenticated client."""
    async with AsyncClient(transport=ASGITransport(app=app_no_calendar), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client(app_no_calendar):
    """Authenticated client with valid session."""
    async with AsyncClient(transport=ASGITransport(app=app_no_calendar), base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={
            "username": "admin",
            "password": "lels1234",
        })
        assert login_resp.status_code == 200
        yield ac


# --- _do_parse_date_range ---

class TestParseDateRange:
    def test_iso_format(self):
        result = _do_parse_date_range("2025-07-15")
        assert "time_min" in result
        assert "time_max" in result
        assert "2025-07-15" in result["time_min"]
        assert "2025-07-15" in result["time_max"]
        assert "T00:00:00" in result["time_min"]
        assert "T23:59:59" in result["time_max"]

    def test_datetime_format(self):
        result = _do_parse_date_range("2025-07-15 14:00")
        assert "time_min" in result
        assert "time_max" in result

    def test_invalid_date(self):
        with pytest.raises(ValueError, match="Could not parse date"):
            _do_parse_date_range("not a date at all xyz123")

    def test_relative_date_next_tuesday(self):
        result = _do_parse_date_range("next Tuesday")
        assert "time_min" in result
        assert "time_max" in result
        assert "T00:00:00" in result["time_min"]
        assert "T23:59:59" in result["time_max"]

    def test_today(self):
        result = _do_parse_date_range("today")
        assert "time_min" in result
        assert "time_max" in result

    def test_this_month(self):
        result = _do_parse_date_range("this month")
        assert "time_min" in result
        assert "time_max" in result


# --- _do_filter ---

class TestDoFilter:
    @patch("main.get_service")
    def test_filter_by_keyword(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting with Ana", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
                {"summary": "Lunch", "start": {"dateTime": "2025-07-01T12:00:00Z"}, "end": {"dateTime": "2025-07-01T13:00:00Z"}},
            ]
        }
        result = _do_filter(keyword="Ana")
        assert len(result) == 1
        assert result[0]["summary"] == "Meeting with Ana"

    @patch("main.get_service")
    def test_filter_by_location(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Standup", "location": "Room A", "start": {"dateTime": "2025-07-01T09:00:00Z"}, "end": {"dateTime": "2025-07-01T09:30:00Z"}},
                {"summary": "Review", "location": "Room B", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        result = _do_filter(location="Room A")
        assert len(result) == 1
        assert result[0]["summary"] == "Standup"

    @patch("main.get_service")
    def test_filter_combined_keyword_and_location(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting with Ana", "location": "Room A", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
                {"summary": "Meeting with Ana", "location": "Room B", "start": {"dateTime": "2025-07-02T10:00:00Z"}, "end": {"dateTime": "2025-07-02T11:00:00Z"}},
                {"summary": "Lunch", "location": "Room A", "start": {"dateTime": "2025-07-01T12:00:00Z"}, "end": {"dateTime": "2025-07-01T13:00:00Z"}},
            ]
        }
        result = _do_filter(keyword="Ana", location="Room A")
        assert len(result) == 1
        assert result[0]["summary"] == "Meeting with Ana"

    @patch("main.get_service")
    def test_filter_by_days(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {"items": []}
        result = _do_filter(days=14)
        assert result == []

    @patch("main.get_service")
    def test_filter_no_results(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        result = _do_filter(keyword="nonexistent")
        assert result == []

    @patch("main.get_service")
    def test_filter_keyword_in_description(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Review", "description": "Discuss Ana's PR", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        result = _do_filter(keyword="Ana")
        assert len(result) == 1

    def test_filter_invalid_days(self):
        with pytest.raises(ValueError, match="days must be between 1 and 365"):
            _do_filter(days=500)

    def test_filter_invalid_days_zero(self):
        with pytest.raises(ValueError, match="days must be between 1 and 365"):
            _do_filter(days=0)

    @patch("main.get_service")
    def test_filter_not_authenticated(self, mock_get_service):
        mock_get_service.side_effect = NotAuthenticated("http://auth.url")
        result = _do_filter(keyword="test")
        assert "error" in result

    @patch("main.get_service")
    def test_filter_case_insensitive_keyword(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting with ANA", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        result = _do_filter(keyword="ana")
        assert len(result) == 1

    @patch("main.get_service")
    def test_filter_case_insensitive_location(self, mock_get_service):
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting", "location": "ROOM A", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        result = _do_filter(location="room a")
        assert len(result) == 1


# --- POST /api/calendar/filter ---

class TestFilterEndpoint:
    @pytest.mark.asyncio
    async def test_filter_unauthenticated(self, client):
        resp = await client.post("/api/calendar/filter", json={})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_filter_not_calendar_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.post("/api/calendar/filter", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True

    @pytest.mark.asyncio
    async def test_filter_with_keyword(self, auth_client):
        with patch("main.get_service") as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            mock_service.events().list().execute.return_value = {
                "items": [
                    {"summary": "Team Standup", "start": {"dateTime": "2025-07-01T09:00:00Z"}, "end": {"dateTime": "2025-07-01T09:30:00Z"}},
                ]
            }
            resp = await auth_client.post("/api/calendar/filter", json={"keyword": "Standup"})
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["events"]) == 1
            assert data["events"][0]["summary"] == "Team Standup"

    @pytest.mark.asyncio
    async def test_filter_with_days(self, auth_client):
        with patch("main.get_service") as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            mock_service.events().list().execute.return_value = {"items": []}
            resp = await auth_client.post("/api/calendar/filter", json={"days": 14})
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_filter_invalid_days_rejected(self, auth_client):
        resp = await auth_client.post("/api/calendar/filter", json={"days": 500})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_filter_default_range(self, auth_client):
        with patch("main.get_service") as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            mock_service.events().list().execute.return_value = {"items": []}
            resp = await auth_client.post("/api/calendar/filter", json={})
            assert resp.status_code == 200
            assert "events" in resp.json()
