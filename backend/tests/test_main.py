import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock
from gcalendar import NotAuthenticated

import auth


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


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "lels1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["username"] == "admin"
        assert data["user"]["id"] == "admin"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrong",
        })
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_login_unknown_user(self, client):
        resp = await client.post("/api/auth/login", json={
            "username": "nobody",
            "password": "anything",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, client):
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_rate_limit(self, client):
        for _ in range(5):
            resp = await client.post("/api/auth/login", json={
                "username": "admin",
                "password": "wrong",
            })
            assert resp.status_code == 401
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "lels1234",
        })
        assert resp.status_code == 429
        assert "Too many login attempts" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_rate_limit_x_forwarded_for(self, client, app_no_calendar):
        for _ in range(5):
            resp = await client.post("/api/auth/login", json={
                "username": "admin",
                "password": "wrong",
            }, headers={"X-Forwarded-For": "1.2.3.4"})
            assert resp.status_code == 401
        resp = await client.post("/api/auth/login", json={
            "username": "admin",
            "password": "lels1234",
        }, headers={"X-Forwarded-For": "1.2.3.4"})
        assert resp.status_code == 429


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_success(self, auth_client):
        resp = await auth_client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Logged out"

    @pytest.mark.asyncio
    async def test_logout_clears_session(self, app_no_calendar):
        async with AsyncClient(transport=ASGITransport(app=app_no_calendar), base_url="http://test") as ac:
            await ac.post("/api/auth/login", json={
                "username": "admin",
                "password": "lels1234",
            })
            await ac.post("/api/auth/logout")
            resp = await ac.get("/api/auth/me")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_unauthenticated(self, client):
        resp = await client.post("/api/auth/logout")
        assert resp.status_code == 401


class TestMe:
    @pytest.mark.asyncio
    async def test_me_success(self, auth_client):
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["username"] == "admin"

    @pytest.mark.asyncio
    async def test_me_unauthenticated(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401


class TestProtectedRoutes:
    @pytest.mark.asyncio
    async def test_chat_unauthenticated(self, client):
        resp = await client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "Hi"}]
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_authenticated(self, auth_client):
        with patch("main.chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "Hello!"
            resp = await auth_client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "Hi"}]
            })
            assert resp.status_code == 200
            assert resp.json() == {"content": "Hello!"}

    @pytest.mark.asyncio
    async def test_calendar_today_unauthenticated(self, client):
        resp = await client.get("/api/calendar/today")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_calendar_today_authenticated(self, auth_client):
        with patch("main.get_service") as mock_get:
            with patch("main.get_today_events", return_value=[]):
                mock_get.return_value = MagicMock()
                resp = await auth_client.get("/api/calendar/today")
                assert resp.status_code == 200
                assert resp.json() == {"events": []}

    @pytest.mark.asyncio
    async def test_calendar_week_unauthenticated(self, client):
        resp = await client.get("/api/calendar/week")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_calendar_week_authenticated(self, auth_client):
        with patch("main.get_service") as mock_get:
            with patch("main.list_events", return_value=[]):
                mock_get.return_value = MagicMock()
                resp = await auth_client.get("/api/calendar/week")
                assert resp.status_code == 200
                assert resp.json() == {"events": []}


class TestCalendarNotAuthenticated:
    """Calendar OAuth not authenticated (different from user auth)."""
    @pytest.mark.asyncio
    async def test_calendar_today_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.get("/api/calendar/today")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True
            assert "auth_url" in data

    @pytest.mark.asyncio
    async def test_calendar_week_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.get("/api/calendar/week")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True
            assert "auth_url" in data

    @pytest.mark.asyncio
    async def test_calendar_auth_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.get("/api/calendar/auth")
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_url"] == "http://auth.url"


class TestCalendarAuthenticated:
    @pytest.fixture
    async def client_cal(self, app_with_calendar):
        async with AsyncClient(transport=ASGITransport(app=app_with_calendar), base_url="http://test") as ac:
            login_resp = await ac.post("/api/auth/login", json={
                "username": "admin",
                "password": "lels1234",
            })
            assert login_resp.status_code == 200
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


class TestOAuthStateValidation:
    @pytest.mark.asyncio
    async def test_callback_missing_state(self, client):
        resp = await client.get("/api/calendar/callback")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_callback_invalid_state(self, auth_client):
        resp = await auth_client.get("/api/calendar/callback?state=randomvalue")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_callback_unauthenticated(self, client):
        resp = await client.get("/api/calendar/callback?state=randomvalue")
        assert resp.status_code == 400
        assert "Invalid or missing state" in resp.text


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


class TestChatValidation:
    @pytest.mark.asyncio
    async def test_chat_invalid_role_rejected(self, auth_client):
        resp = await auth_client.post("/api/chat", json={
            "messages": [{"role": "invalid", "content": "Hi"}]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_missing_content_rejected(self, auth_client):
        resp = await auth_client.post("/api/chat", json={
            "messages": [{"role": "user"}]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_too_many_messages_rejected(self, auth_client):
        resp = await auth_client.post("/api/chat", json={
            "messages": [{"role": "user", "content": "x"} for _ in range(51)]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_empty_body_rejected(self, auth_client):
        resp = await auth_client.post("/api/chat", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_chat_llm_error(self, auth_client):
        from llm import LLMError
        with patch("main.chat", new_callable=AsyncMock, side_effect=LLMError("API down")):
            resp = await auth_client.post("/api/chat", json={
                "messages": [{"role": "user", "content": "Hi"}]
            })
            assert resp.status_code == 200
            assert resp.json()["error"] == "API down"


class TestSessionPersistence:
    @pytest.mark.asyncio
    async def test_session_persists_across_requests(self, auth_client):
        resp1 = await auth_client.get("/api/auth/me")
        assert resp1.status_code == 200
        resp2 = await auth_client.get("/api/auth/me")
        assert resp2.status_code == 200

    @pytest.mark.asyncio
    async def test_session_cookie_is_http_only(self, app_no_calendar):
        async with AsyncClient(transport=ASGITransport(app=app_no_calendar), base_url="http://test") as ac:
            resp = await ac.post("/api/auth/login", json={
                "username": "admin",
                "password": "lels1234",
            })
            assert resp.status_code == 200
            set_cookie = resp.headers["set-cookie"]
            assert "httponly" in set_cookie.lower()


class TestRateLimiter:
    def test_rate_limiter_allows_under_limit(self):
        limiter = auth.RateLimiter(max_attempts=3, window_seconds=60)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        for _ in range(3):
            assert limiter.is_limited(mock_request) is False

    def test_rate_limiter_blocks_over_limit(self):
        limiter = auth.RateLimiter(max_attempts=3, window_seconds=60)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        for _ in range(3):
            limiter.is_limited(mock_request)
        assert limiter.is_limited(mock_request) is True

    def test_rate_limiter_x_forwarded_for(self):
        limiter = auth.RateLimiter(max_attempts=2, window_seconds=60)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
        limiter.is_limited(mock_request)
        limiter.is_limited(mock_request)
        assert limiter.is_limited(mock_request) is True

    def test_rate_limiter_different_ips_independent(self):
        limiter = auth.RateLimiter(max_attempts=1, window_seconds=60)
        req1 = MagicMock()
        req1.client.host = "1.1.1.1"
        req1.headers = {}
        req2 = MagicMock()
        req2.client.host = "2.2.2.2"
        req2.headers = {}
        limiter.is_limited(req1)
        assert limiter.is_limited(req1) is True
        assert limiter.is_limited(req2) is False
