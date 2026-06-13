import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock


@pytest.fixture
async def client(app_with_calendar):
    async with AsyncClient(transport=ASGITransport(app=app_with_calendar), base_url="http://test") as ac:
        yield ac


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

    @pytest.mark.asyncio
    async def test_callback_missing_state(self, client):
        resp = await client.get("/api/calendar/callback", params={})
        assert resp.status_code == 422


class TestAuthFlow:
    @pytest.mark.asyncio
    async def test_calendar_auth_when_authenticated(self, client):
        mock_service = MagicMock()

        with patch("main.get_service") as mock_get:
            mock_get.return_value = mock_service
            resp = await client.get("/api/calendar/auth")
            assert resp.status_code == 200
            assert resp.json() == {"error": "Already authenticated"}
