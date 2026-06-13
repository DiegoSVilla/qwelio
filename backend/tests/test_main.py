import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from gcalendar import NotAuthenticated


@pytest.fixture
async def client(app_no_calendar):
    async with AsyncClient(transport=ASGITransport(app=app_no_calendar), base_url="http://test") as ac:
        yield ac


class TestChatEndpoint:
    @pytest.mark.asyncio
    async def test_chat_success(self, client):
        with patch("main.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "Hello!"
            resp = await client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "Hi"}]
            })
            assert resp.status_code == 200
            assert resp.json() == {"content": "Hello!"}

    @pytest.mark.asyncio
    async def test_chat_llm_error(self, client):
        from llm import LLMError
        with patch("main.chat", new_callable=AsyncMock, side_effect=LLMError("API down")):
            resp = await client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "Hi"}]
            })
            assert resp.status_code == 200
            assert resp.json()["error"] == "API down"

    @pytest.mark.asyncio
    async def test_chat_invalid_role_rejected(self, client):
        resp = await client.post("/api/chat", json={
            "messages": [{"role": "invalid", "content": "Hi"}]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_missing_content_rejected(self, client):
        resp = await client.post("/api/chat", json={
            "messages": [{"role": "user"}]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_too_many_messages_rejected(self, client):
        resp = await client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "x"} for _ in range(51)]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_empty_body_rejected(self, client):
        resp = await client.post("/api/chat", json={})
        assert resp.status_code == 422


class TestCalendarNotAuthenticated:
    @pytest.mark.asyncio
    async def test_calendar_today_not_auth(self, client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await client.get("/api/calendar/today")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True
            assert "auth_url" in data

    @pytest.mark.asyncio
    async def test_calendar_week_not_auth(self, client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await client.get("/api/calendar/week")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True
            assert "auth_url" in data

    @pytest.mark.asyncio
    async def test_calendar_auth_not_auth(self, client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await client.get("/api/calendar/auth")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_url"] == "http://auth.url"


class TestCalendarAuthenticated:
    @pytest.fixture
    async def client_cal(self, app_with_calendar):
        async with AsyncClient(transport=ASGITransport(app=app_with_calendar), base_url="http://test") as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_calendar_today_success(self, client_cal):
        mock_service = MagicMock()
        mock_events = [{"summary": "Test Event", "start": {"dateTime": "2025-01-01T10:00:00Z"}}]

        with patch("main.get_service", return_value=mock_service):
            with patch("main.get_today_events", return_value=mock_events) as mock_today:
                resp = await client_cal.get("/api/calendar/today")
                assert resp.status_code == 200
                data = resp.json()
                assert data["events"] == mock_events
                mock_today.assert_called_once_with(mock_service)

    @pytest.mark.asyncio
    async def test_calendar_week_success(self, client_cal):
        mock_service = MagicMock()
        mock_events = [{"summary": "Meeting", "start": {"dateTime": "2025-01-01T09:00:00Z"}}]

        with patch("main.get_service", return_value=mock_service):
            with patch("main.list_events", return_value=mock_events) as mock_list:
                resp = await client_cal.get("/api/calendar/week")
                assert resp.status_code == 200
                data = resp.json()
                assert data["events"] == mock_events
                mock_list.assert_called_once_with(mock_service, days=7)

    @pytest.mark.asyncio
    async def test_calendar_auth_already_authenticated(self, client_cal):
        mock_service = MagicMock()
        with patch("main.get_service", return_value=mock_service):
            resp = await client_cal.get("/api/calendar/auth")
            assert resp.status_code == 200
            assert resp.json() == {"error": "Already authenticated"}


class TestCORS:
    @pytest.mark.asyncio
    async def test_cors_allowed_origin(self, client):
        resp = await client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        assert "Access-Control-Allow-Origin" in resp.headers

    @pytest.mark.asyncio
    async def test_cors_blocked_origin(self, client):
        resp = await client.options(
            "/api/chat",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "Access-Control-Allow-Origin" not in resp.headers
