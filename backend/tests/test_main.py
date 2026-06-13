import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
import os
from gcalendar import NotAuthenticated


@pytest.fixture
def app():
    with patch.dict(os.environ, {
        "QWEN_API_KEY": "test-key",
        "QWEN_API_URL": "https://test.example.com/v1",
        "MODEL_NAME": "test-model",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
    }):
        from main import app
        yield app


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
            assert "auth_url" in data


class TestCalendarAuthenticated:
    @pytest.mark.asyncio
    async def test_calendar_today_success(self, client):
        mock_service = MagicMock()
        mock_events = [{"summary": "Test Event", "start": {"dateTime": "2025-01-01T10:00:00Z"}}]

        with patch("main.get_service", return_value=mock_service):
            with patch("main.get_today_events", return_value=mock_events):
                resp = await client.get("/api/calendar/today")
                assert resp.status_code == 200
                data = resp.json()
                assert data["events"] == mock_events

    @pytest.mark.asyncio
    async def test_calendar_week_success(self, client):
        mock_service = MagicMock()
        mock_events = [{"summary": "Meeting", "start": {"dateTime": "2025-01-01T09:00:00Z"}}]

        with patch("main.get_service", return_value=mock_service):
            with patch("main.list_events", return_value=mock_events):
                resp = await client.get("/api/calendar/week")
                assert resp.status_code == 200
                data = resp.json()
                assert data["events"] == mock_events

    @pytest.mark.asyncio
    async def test_calendar_auth_already_authenticated(self, client):
        mock_service = MagicMock()
        with patch("main.get_service", return_value=mock_service):
            resp = await client.get("/api/calendar/auth")
            assert resp.status_code == 200
            assert resp.json() == {"error": "Already authenticated"}


class TestCalendarCallback:
    @pytest.mark.asyncio
    async def test_callback_success(self, client):
        mock_service = MagicMock()
        with patch("main.auth_flow") as mock_auth:
            mock_auth.return_value = mock_service
            resp = await client.get("/api/calendar/callback", params={
                "state": "https://accounts.google.com/o/oauth2/auth?response_type=code&..."
            })
            assert resp.status_code == 200
            assert "Success!" in resp.text
            assert "Calendar authorized" in resp.text

    @pytest.mark.asyncio
    async def test_callback_failure(self, client):
        with patch("main.auth_flow") as mock_auth:
            mock_auth.side_effect = Exception("OAuth failed")
            resp = await client.get("/api/calendar/callback", params={
                "state": "https://accounts.google.com/o/oauth2/auth?response_type=code&..."
            })
            assert resp.status_code == 500
            assert "Error" in resp.text
            assert "Authorization failed" in resp.text


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
