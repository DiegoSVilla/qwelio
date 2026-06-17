import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock
from gcalendar import NotAuthenticated


@pytest.fixture
async def client(app_with_calendar):
    async with AsyncClient(transport=ASGITransport(app=app_with_calendar), base_url="http://test") as ac:
        login_resp = await ac.post("/api/auth/login", json={
            "username": "admin",
            "password": "lels1234",
        })
        assert login_resp.status_code == 200
        yield ac


class TestCalendarCallback:
    @pytest.mark.asyncio
    async def test_callback_success(self, client):
        mock_service = MagicMock()
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            auth_resp = await client.get("/api/calendar/auth")
            assert auth_resp.status_code == 200
            auth_data = auth_resp.json()
            assert "oauth_state" in auth_data

        with patch("main.auth_flow") as mock_auth:
            mock_auth.return_value = mock_service
            resp = await client.get("/api/calendar/callback", params={"state": auth_data["oauth_state"]})
            assert resp.status_code == 200
            assert "Success!" in resp.text
            assert "Calendar connected" in resp.text
            call_arg = mock_auth.call_args[0][0]
            assert "/api/calendar/callback" in call_arg
            assert "state=" in call_arg

    @pytest.mark.asyncio
    async def test_callback_failure(self, client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            auth_resp = await client.get("/api/calendar/auth")
            auth_data = auth_resp.json()

        with patch("main.auth_flow") as mock_auth:
            mock_auth.side_effect = Exception("OAuth failed")
            resp = await client.get("/api/calendar/callback", params={"state": auth_data["oauth_state"]})
            assert resp.status_code == 500
            assert "Error" in resp.text
            assert "Authorization failed" in resp.text

    @pytest.mark.asyncio
    async def test_callback_missing_state(self, client):
        resp = await client.get("/api/calendar/callback", params={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_callback_invalid_state(self, client):
        resp = await client.get("/api/calendar/callback", params={"state": "randomvalue"})
        assert resp.status_code == 400
        assert "Invalid or missing state" in resp.text


class TestAuthFlow:
    @pytest.mark.asyncio
    async def test_calendar_auth_when_authenticated(self, client):
        mock_service = MagicMock()
        with patch("main.get_service") as mock_get:
            mock_get.return_value = mock_service
            resp = await client.get("/api/calendar/auth")
            assert resp.status_code == 200
            assert resp.json() == {"error": "Already authenticated"}

    @pytest.mark.asyncio
    async def test_calendar_auth_when_not_authenticated(self, client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await client.get("/api/calendar/auth")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_url"] == "http://auth.url"
            assert "oauth_state" in data
