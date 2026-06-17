import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

from main import _do_filter
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


# --- _do_filter ---

class TestDoFilter:
    @pytest.mark.asyncio
    async def test_filter_by_keyword(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting with Ana", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
                {"summary": "Lunch", "start": {"dateTime": "2025-07-01T12:00:00Z"}, "end": {"dateTime": "2025-07-01T13:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(keyword="Ana")
            assert len(result["events"]) == 1
            assert result["events"][0]["summary"] == "Meeting with Ana"

    @pytest.mark.asyncio
    async def test_filter_by_location(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Standup", "location": "Room A", "start": {"dateTime": "2025-07-01T09:00:00Z"}, "end": {"dateTime": "2025-07-01T09:30:00Z"}},
                {"summary": "Review", "location": "Room B", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(location="Room A")
            assert len(result["events"]) == 1
            assert result["events"][0]["summary"] == "Standup"

    @pytest.mark.asyncio
    async def test_filter_combined_keyword_and_location(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting with Ana", "location": "Room A", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
                {"summary": "Meeting with Ana", "location": "Room B", "start": {"dateTime": "2025-07-02T10:00:00Z"}, "end": {"dateTime": "2025-07-02T11:00:00Z"}},
                {"summary": "Lunch", "location": "Room A", "start": {"dateTime": "2025-07-01T12:00:00Z"}, "end": {"dateTime": "2025-07-01T13:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(keyword="Ana", location="Room A")
            assert len(result["events"]) == 1
            assert result["events"][0]["summary"] == "Meeting with Ana"

    @pytest.mark.asyncio
    async def test_filter_by_days(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {"items": []}
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(days=14)
            assert result == {"events": []}

    @pytest.mark.asyncio
    async def test_filter_no_results(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(keyword="nonexistent")
            assert result == {"events": []}

    @pytest.mark.asyncio
    async def test_filter_by_time_min_time_max(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"id": "evt1", "summary": "Meeting", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(time_min="2025-07-01T00:00:00Z", time_max="2025-07-07T00:00:00Z")
            assert len(result["events"]) == 1
            assert result["events"][0]["id"] == "evt1"

    @pytest.mark.asyncio
    async def test_filter_time_min_after_time_max_raises(self):
        with pytest.raises(ValueError, match="time_min must be before time_max"):
            await _do_filter(time_min="2025-07-07T00:00:00Z", time_max="2025-07-01T00:00:00Z")

    @pytest.mark.asyncio
    async def test_filter_time_min_after_time_max_mixed_tz(self):
        with pytest.raises(ValueError, match="time_min must be before time_max"):
            await _do_filter(time_min="2025-07-01T10:00:00+05:00", time_max="2025-07-01T04:00:00+00:00")

    @pytest.mark.asyncio
    async def test_filter_time_min_equal_time_max_raises(self):
        with pytest.raises(ValueError, match="time_min must be before time_max"):
            await _do_filter(time_min="2025-07-01T00:00:00Z", time_max="2025-07-01T00:00:00Z")

    @pytest.mark.asyncio
    async def test_filter_event_has_id(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"id": "abc123", "summary": "Test", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(keyword="Test")
            assert result["events"][0]["id"] == "abc123"

    @pytest.mark.asyncio
    async def test_filter_keyword_in_description(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Review", "description": "Discuss Ana's PR", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(keyword="Ana")
            assert len(result["events"]) == 1

    @pytest.mark.asyncio
    async def test_filter_invalid_days(self):
        with pytest.raises(ValueError, match="days must be between 1 and 365"):
            await _do_filter(days=500)

    @pytest.mark.asyncio
    async def test_filter_invalid_days_zero(self):
        with pytest.raises(ValueError, match="days must be between 1 and 365"):
            await _do_filter(days=0)

    @pytest.mark.asyncio
    async def test_filter_not_authenticated(self):
        with patch("main.get_service", new_callable=AsyncMock, side_effect=NotAuthenticated("http://auth.url")):
            result = await _do_filter(keyword="test")
            assert "error" in result

    @pytest.mark.asyncio
    async def test_filter_case_insensitive_keyword(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting with ANA", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(keyword="ana")
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filter_case_insensitive_location(self):
        mock_service = MagicMock()
        mock_service.events().list().execute.return_value = {
            "items": [
                {"summary": "Meeting", "location": "ROOM A", "start": {"dateTime": "2025-07-01T10:00:00Z"}, "end": {"dateTime": "2025-07-01T11:00:00Z"}},
            ]
        }
        with patch("main.get_service", new_callable=AsyncMock, return_value=mock_service):
            result = await _do_filter(location="room a")
            assert len(result) == 1


# --- POST /api/calendar/filter ---

class TestFilterEndpoint:
    @pytest.mark.asyncio
    async def test_filter_unauthenticated(self, client):
        resp = await client.post("/api/calendar/filter", json={})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_filter_not_calendar_auth(self, auth_client):
        with patch("main.get_service", new_callable=AsyncMock, side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.post("/api/calendar/filter", json={})
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True

    @pytest.mark.asyncio
    async def test_filter_with_keyword(self, auth_client):
        with patch("main.get_service", new_callable=AsyncMock) as mock_get_service:
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
        with patch("main.get_service", new_callable=AsyncMock) as mock_get_service:
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
        with patch("main.get_service", new_callable=AsyncMock) as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            mock_service.events().list().execute.return_value = {"items": []}
            resp = await auth_client.post("/api/calendar/filter", json={})
            assert resp.status_code == 200
            assert "events" in resp.json()

    @pytest.mark.asyncio
    async def test_filter_days_and_time_min_rejected(self, auth_client):
        resp = await auth_client.post("/api/calendar/filter", json={"days": 14, "time_min": "2025-07-01T00:00:00Z"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_filter_time_min_after_time_max_rejected(self, auth_client):
        resp = await auth_client.post("/api/calendar/filter", json={"time_min": "2025-07-07T00:00:00Z", "time_max": "2025-07-01T00:00:00Z"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_filter_time_min_equal_time_max_rejected(self, auth_client):
        resp = await auth_client.post("/api/calendar/filter", json={"time_min": "2025-07-01T00:00:00Z", "time_max": "2025-07-01T00:00:00Z"})
        assert resp.status_code == 422
