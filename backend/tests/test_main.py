import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock, Mock
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

    @pytest.mark.asyncio
    async def test_login_success_not_rate_limited(self, client):
        """Successful logins should not count against rate limit."""
        for _ in range(10):
            resp = await client.post("/api/auth/login", json={
                "username": "admin",
                "password": "lels1234",
            })
            assert resp.status_code == 200


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
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock):
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    mock_history.return_value = []
                    mock_chat.return_value = ("Hello!", [])
                    resp = await auth_client.post("/api/chat", json={
                        "messages": [{"role": "user", "content": "Hi"}]
                    })
                    assert resp.status_code == 200
                    assert resp.json() == {"content": "Hello!", "tool_calls": []}

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
    async def test_callback_missing_state(self, auth_client):
        resp = await auth_client.get("/api/calendar/callback")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_callback_invalid_state(self, auth_client):
        resp = await auth_client.get("/api/calendar/callback?state=randomvalue")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_callback_unauthenticated(self, client):
        resp = await client.get("/api/calendar/callback?state=randomvalue")
        assert resp.status_code == 401


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
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock):
                with patch("main.chat_with_tools", new_callable=AsyncMock, side_effect=LLMError("API down")):
                    mock_history.return_value = []
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

    @pytest.mark.asyncio
    async def test_session_cookie_is_samesite_lax(self, app_no_calendar):
        async with AsyncClient(transport=ASGITransport(app=app_no_calendar), base_url="http://test") as ac:
            resp = await ac.post("/api/auth/login", json={
                "username": "admin",
                "password": "lels1234",
            })
            assert resp.status_code == 200
            set_cookie = resp.headers["set-cookie"]
            assert "samesite=lax" in set_cookie.lower()


class TestRateLimiter:
    def test_rate_limiter_allows_under_limit(self):
        limiter = auth.RateLimiter(max_attempts=3, window_seconds=60)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        for _ in range(3):
            assert limiter.is_limited(mock_request) is False
            limiter.record(mock_request)

    def test_rate_limiter_blocks_over_limit(self):
        limiter = auth.RateLimiter(max_attempts=3, window_seconds=60)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        for _ in range(3):
            limiter.record(mock_request)
        assert limiter.is_limited(mock_request) is True

    def test_rate_limiter_x_forwarded_for(self):
        limiter = auth.RateLimiter(max_attempts=2, window_seconds=60)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {"X-Forwarded-For": "10.0.0.1, 10.0.0.2"}
        limiter.record(mock_request)
        limiter.record(mock_request)
        assert limiter.is_limited(mock_request) is True

    def test_rate_limiter_different_ips_independent(self):
        limiter = auth.RateLimiter(max_attempts=1, window_seconds=60)
        req1 = MagicMock()
        req1.client.host = "1.1.1.1"
        req1.headers = {}
        req2 = MagicMock()
        req2.client.host = "2.2.2.2"
        req2.headers = {}
        limiter.record(req1)
        assert limiter.is_limited(req1) is True
        assert limiter.is_limited(req2) is False

    def test_rate_limiter_cleanup(self):
        limiter = auth.RateLimiter(max_attempts=2, window_seconds=1)
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        limiter.record(mock_request)
        limiter.record(mock_request)
        assert limiter.is_limited(mock_request) is True
        import time
        time.sleep(1.1)
        assert limiter.is_limited(mock_request) is False

    @pytest.mark.asyncio
    async def test_verify_password_correct(self):
        import bcrypt
        fake_hash = bcrypt.hashpw(b"lels1234", bcrypt.gensalt()).decode()
        with patch("storage.get_user_by_username", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = (1, "admin", fake_hash)
            assert await auth.verify_password("admin", "lels1234") is True

    @pytest.mark.asyncio
    async def test_verify_password_wrong(self):
        import bcrypt
        fake_hash = bcrypt.hashpw(b"lels1234", bcrypt.gensalt()).decode()
        with patch("storage.get_user_by_username", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = (1, "admin", fake_hash)
            assert await auth.verify_password("admin", "wrong") is False

    @pytest.mark.asyncio
    async def test_verify_password_unknown_user(self):
        with patch("storage.get_user_by_username", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            assert await auth.verify_password("nobody", "anything") is False

    @pytest.mark.asyncio
    async def test_verify_password_empty_string(self):
        import bcrypt
        fake_hash = bcrypt.hashpw(b"lels1234", bcrypt.gensalt()).decode()
        with patch("storage.get_user_by_username", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = (1, "admin", fake_hash)
            assert await auth.verify_password("admin", "") is False

    @pytest.mark.asyncio
    async def test_verify_password_unknown_empty(self):
        with patch("storage.get_user_by_username", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            assert await auth.verify_password("nobody", "") is False


class TestCalendarStatus:
    @pytest.mark.asyncio
    async def test_calendar_status_connected(self, auth_client):
        with patch("main.get_service", return_value=MagicMock()):
            resp = await auth_client.get("/api/calendar/status")
            assert resp.status_code == 200
            assert resp.json()["connected"] is True

    @pytest.mark.asyncio
    async def test_calendar_status_not_connected(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.get("/api/calendar/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is False
            assert "auth_url" in data

    @pytest.mark.asyncio
    async def test_calendar_status_unauthenticated(self, client):
        resp = await client.get("/api/calendar/status")
        assert resp.status_code == 401


class TestCalendarMonth:
    @pytest.mark.asyncio
    async def test_calendar_month_success(self, auth_client):
        with patch("main.get_service", return_value=MagicMock()):
            with patch("main.get_month_events", return_value=[{"summary": "Test"}]):
                resp = await auth_client.get("/api/calendar/month?year=2025&month=6")
                assert resp.status_code == 200
                assert len(resp.json()["events"]) == 1

    @pytest.mark.asyncio
    async def test_calendar_month_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.get("/api/calendar/month?year=2025&month=6")
            assert resp.status_code == 200
            assert resp.json()["auth_required"] is True

    @pytest.mark.asyncio
    async def test_calendar_month_unauthenticated(self, client):
        resp = await client.get("/api/calendar/month?year=2025&month=6")
        assert resp.status_code == 401


class TestCalendarDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_calendar(self, auth_client):
        with patch("main.disconnect_calendar", return_value={"disconnected": True}):
            resp = await auth_client.delete("/api/calendar/disconnect")
            assert resp.status_code == 200
            assert resp.json()["disconnected"] is True

    @pytest.mark.asyncio
    async def test_disconnect_not_connected(self, auth_client):
        with patch("main.disconnect_calendar", return_value={"error": "Calendar not connected"}):
            resp = await auth_client.delete("/api/calendar/disconnect")
            assert resp.status_code == 200
            assert "error" in resp.json()

    @pytest.mark.asyncio
    async def test_disconnect_unauthenticated(self, client):
        resp = await client.delete("/api/calendar/disconnect")
        assert resp.status_code == 401


class TestTimezones:
    @pytest.mark.asyncio
    async def test_get_timezones(self, auth_client):
        resp = await auth_client.get("/api/timezones")
        assert resp.status_code == 200
        data = resp.json()
        assert "timezones" in data
        assert "UTC" in data["timezones"]

    @pytest.mark.asyncio
    async def test_timezones_unauthenticated(self, client):
        resp = await client.get("/api/timezones")
        assert resp.status_code == 401


class TestSettingsUpdate:
    @pytest.mark.asyncio
    async def test_update_timezone(self, auth_client):
        with patch("main.update_user_timezone", new_callable=AsyncMock):
            resp = await auth_client.patch("/api/settings", json={"timezone": "UTC-5"})
            assert resp.status_code == 200
            assert resp.json()["updated"] is True

    @pytest.mark.asyncio
    async def test_update_timezone_persists(self, auth_client):
        """Full round-trip: PATCH timezone -> GET settings -> verify persisted."""
        resp = await auth_client.patch("/api/settings", json={"timezone": "UTC-3"})
        assert resp.status_code == 200, f"PATCH failed: {resp.text}"
        assert resp.json()["updated"] is True

        settings_resp = await auth_client.get("/api/settings")
        assert settings_resp.status_code == 200, f"GET settings failed: {settings_resp.text}"
        data = settings_resp.json()
        assert data["timezone"] == "UTC-3", f"Expected UTC-3, got {data['timezone']}"

    @pytest.mark.asyncio
    async def test_update_timezone_reflects_in_me(self, auth_client):
        """After PATCH timezone, /api/auth/me should reflect the new value."""
        resp = await auth_client.patch("/api/settings", json={"timezone": "UTC-4"})
        assert resp.status_code == 200, f"PATCH failed: {resp.text}"

        me_resp = await auth_client.get("/api/auth/me")
        assert me_resp.status_code == 200, f"GET /me failed: {me_resp.text}"
        me_data = me_resp.json()
        assert me_data["timezone"] == "UTC-4", f"Expected UTC-4, got {me_data['timezone']}"

    @pytest.mark.asyncio
    async def test_update_invalid_timezone(self, auth_client):
        resp = await auth_client.patch("/api/settings", json={"timezone": "Invalid/Zone"})
        assert resp.status_code == 400
        assert "Invalid timezone" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_settings_unauthenticated(self, client):
        resp = await client.patch("/api/settings", json={"timezone": "UTC"})
        assert resp.status_code == 401


class TestMeWithTimezone:
    @pytest.mark.asyncio
    async def test_me_returns_timezone(self, auth_client):
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert "timezone" in data


class TestCalendarWriteEndpoints:
    @pytest.mark.asyncio
    async def test_create_event_unauthenticated(self, client):
        resp = await client.post("/api/calendar/events", json={
            "summary": "Meeting",
            "start": "2025-01-01T10:00:00Z",
            "end": "2025-01-01T11:00:00Z",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_event_missing_fields(self, auth_client):
        resp = await auth_client.post("/api/calendar/events", json={
            "summary": "Meeting",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_event_success(self, auth_client):
        mock_service = MagicMock()
        mock_event = {"id": "evt-123", "status": "confirmed"}
        with patch("main.get_service", return_value=mock_service):
            with patch("main.create_event", return_value=mock_event):
                resp = await auth_client.post("/api/calendar/events", json={
                    "summary": "Meeting",
                    "start": "2025-01-01T10:00:00Z",
                    "end": "2025-01-01T11:00:00Z",
                    "location": "Room A",
                    "description": "Sync up",
                })
                assert resp.status_code == 201
                data = resp.json()
                assert data["id"] == "evt-123"
                assert data["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_create_event_duplicate(self, auth_client):
        mock_service = MagicMock()
        with patch("main.get_service", return_value=mock_service):
            with patch("main.create_event", side_effect=ValueError("Duplicate event: Meeting")):
                resp = await auth_client.post("/api/calendar/events", json={
                    "summary": "Meeting",
                    "start": "2025-01-01T10:00:00Z",
                    "end": "2025-01-01T11:00:00Z",
                })
                assert resp.status_code == 409
                assert "Duplicate" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_event_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.post("/api/calendar/events", json={
                "summary": "Meeting",
                "start": "2025-01-01T10:00:00Z",
                "end": "2025-01-01T11:00:00Z",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["auth_required"] is True

    @pytest.mark.asyncio
    async def test_create_event_invalid_iso8601(self, auth_client):
        resp = await auth_client.post("/api/calendar/events", json={
            "summary": "Test",
            "start": "not-a-date",
            "end": "2025-01-01T11:00:00Z",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_event_end_before_start(self, auth_client):
        resp = await auth_client.post("/api/calendar/events", json={
            "summary": "Test",
            "start": "2025-01-01T12:00:00Z",
            "end": "2025-01-01T10:00:00Z",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_event_empty_summary(self, auth_client):
        resp = await auth_client.post("/api/calendar/events", json={
            "summary": "",
            "start": "2025-01-01T10:00:00Z",
            "end": "2025-01-01T11:00:00Z",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_event_summary_too_long(self, auth_client):
        resp = await auth_client.post("/api/calendar/events", json={
            "summary": "x" * 1025,
            "start": "2025-01-01T10:00:00Z",
            "end": "2025-01-01T11:00:00Z",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_event_mixed_date_datetime(self, auth_client):
        mock_service = MagicMock()
        mock_event = {"id": "evt-mixed", "status": "confirmed"}
        with patch("main.get_service", return_value=mock_service):
            with patch("main.create_event", return_value=mock_event):
                resp = await auth_client.post("/api/calendar/events", json={
                    "summary": "Test",
                    "start": "2025-01-01",
                    "end": "2025-01-01T10:00:00Z",
                })
                assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_edit_event_invalid_iso8601(self, auth_client):
        resp = await auth_client.patch("/api/calendar/events/evt-123", json={
            "start": "not-a-date",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_edit_event_end_before_start(self, auth_client):
        resp = await auth_client.patch("/api/calendar/events/evt-123", json={
            "start": "2025-01-01T12:00:00Z",
            "end": "2025-01-01T10:00:00Z",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_edit_event_unauthenticated(self, client):
        resp = await client.patch("/api/calendar/events/evt-123", json={
            "summary": "Updated Meeting",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_edit_event_success(self, auth_client):
        mock_service = MagicMock()
        mock_updated = {"id": "evt-123"}
        with patch("main.get_service", return_value=mock_service):
            with patch("main.edit_event", return_value=mock_updated):
                resp = await auth_client.patch("/api/calendar/events/evt-123", json={
                    "summary": "Updated Meeting",
                    "location": "Room B",
                })
                assert resp.status_code == 200
                assert resp.json()["id"] == "evt-123"

    @pytest.mark.asyncio
    async def test_edit_event_not_found(self, auth_client):
        mock_service = MagicMock()
        with patch("main.get_service", return_value=mock_service):
            with patch("main.edit_event", side_effect=KeyError("Event evt-999 not found")):
                resp = await auth_client.patch("/api/calendar/events/evt-999", json={
                    "summary": "Updated",
                })
                assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_event_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.patch("/api/calendar/events/evt-123", json={
                "summary": "Updated",
            })
            assert resp.status_code == 200
            assert resp.json()["auth_required"] is True

    @pytest.mark.asyncio
    async def test_delete_event_unauthenticated(self, client):
        resp = await client.delete("/api/calendar/events/evt-123")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_event_success(self, auth_client):
        mock_service = MagicMock()
        with patch("main.get_service", return_value=mock_service):
            with patch("main.delete_event") as mock_delete:
                resp = await auth_client.delete("/api/calendar/events/evt-123")
                assert resp.status_code == 200
                assert resp.json()["deleted"] == "evt-123"
                mock_delete.assert_called_once_with(mock_service, "evt-123")

    @pytest.mark.asyncio
    async def test_delete_event_not_found(self, auth_client):
        mock_service = MagicMock()
        with patch("main.get_service", return_value=mock_service):
            with patch("main.delete_event", side_effect=KeyError("Event evt-999 not found")):
                resp = await auth_client.delete("/api/calendar/events/evt-999")
                assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_event_not_auth(self, auth_client):
        with patch("main.get_service", side_effect=NotAuthenticated("http://auth.url")):
            resp = await auth_client.delete("/api/calendar/events/evt-123")
            assert resp.status_code == 200
            assert resp.json()["auth_required"] is True


class TestGcalendarWriteFunctions:
    def test_to_gapi_event_with_datetime(self):
        from gcalendar import _to_gapi_event
        result = _to_gapi_event("Meeting", "2025-01-01T10:00:00Z", "2025-01-01T11:00:00Z", "Room A", "Sync")
        assert result["summary"] == "Meeting"
        assert result["start"] == {"dateTime": "2025-01-01T10:00:00Z"}
        assert result["end"] == {"dateTime": "2025-01-01T11:00:00Z"}
        assert result["location"] == "Room A"
        assert result["description"] == "Sync"

    def test_to_gapi_event_all_day(self):
        from gcalendar import _to_gapi_event
        result = _to_gapi_event("Holiday", "2025-01-01", "2025-01-02")
        assert result["start"] == {"date": "2025-01-01"}
        assert result["end"] == {"date": "2025-01-02"}
        assert "location" not in result
        assert "description" not in result

    def test_create_event_success(self):
        from gcalendar import create_event
        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.return_value = {"items": []}
        mock_service.events.return_value.insert.return_value.execute.return_value = {"id": "evt-123", "status": "confirmed"}
        result = create_event(mock_service, "Meeting", "2025-01-01T10:00:00Z", "2025-01-01T11:00:00Z")
        assert result["id"] == "evt-123"

    def test_create_event_duplicate(self):
        from gcalendar import create_event
        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"summary": "Meeting", "start": {"dateTime": "2025-01-01T10:00:00Z"}}]
        }
        with pytest.raises(ValueError, match="Duplicate"):
            create_event(mock_service, "meeting", "2025-01-01T10:00:00Z", "2025-01-01T11:00:00Z")

    def test_edit_event_success(self):
        from gcalendar import edit_event
        mock_service = MagicMock()
        mock_service.events.return_value.get.return_value.execute.return_value = {"id": "evt-123", "summary": "Old", "start": {"date": "2025-01-01"}, "end": {"date": "2025-01-02"}}
        mock_service.events.return_value.patch.return_value.execute.return_value = {"id": "evt-123", "summary": "New"}
        result = edit_event(mock_service, "evt-123", summary="New")
        assert result["summary"] == "New"

    def test_edit_event_not_found(self):
        from gcalendar import edit_event
        from googleapiclient.errors import HttpError
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_error = HttpError(Mock(status=404), b"Not found")
        mock_service.events.return_value.get.return_value.execute.side_effect = mock_error
        with pytest.raises(KeyError, match="not found"):
            edit_event(mock_service, "evt-999", summary="New")

    def test_delete_event_success(self):
        from gcalendar import delete_event
        mock_service = MagicMock()
        delete_event(mock_service, "evt-123")
        mock_service.events.return_value.delete.assert_called_once()

    def test_delete_event_not_found(self):
        from gcalendar import delete_event
        from googleapiclient.errors import HttpError
        from unittest.mock import MagicMock
        mock_service = MagicMock()
        mock_error = HttpError(Mock(status=404), b"Not found")
        mock_service.events.return_value.delete.return_value.execute.side_effect = mock_error
        with pytest.raises(KeyError, match="not found"):
            delete_event(mock_service, "evt-999")


class TestConversationEndpoints:
    @pytest.mark.asyncio
    async def test_get_conversations_unauthenticated(self, client):
        resp = await client.get("/api/conversations")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_conversations_success(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.get_summaries", new_callable=AsyncMock) as mock_summaries:
                mock_history.return_value = [{"role": "user", "content": "Hi", "tool_calls": None, "tool_call_id": None, "turn_order": 1}]
                mock_summaries.return_value = {"monthly": [], "weekly": [], "daily": []}
                resp = await auth_client.get("/api/conversations")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["history"]) == 1
                assert data["summaries"]["monthly"] == []
                mock_history.assert_called_once()
                mock_summaries.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_conversations_limit_param(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.get_summaries", new_callable=AsyncMock) as mock_summaries:
                mock_history.return_value = []
                mock_summaries.return_value = {"monthly": [], "weekly": [], "daily": []}
                resp = await auth_client.get("/api/conversations?limit=10")
                assert resp.status_code == 200
                assert mock_history.call_args[1]["limit"] == 10

    @pytest.mark.asyncio
    async def test_get_conversations_limit_too_high(self, client):
        async with AsyncClient(transport=ASGITransport(app=client._transport.app), base_url="http://test") as ac:
            await ac.post("/api/auth/login", json={"username": "admin", "password": "lels1234"})
            resp = await ac.get("/api/conversations?limit=201")
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_conversations_limit_too_low(self, client):
        async with AsyncClient(transport=ASGITransport(app=client._transport.app), base_url="http://test") as ac:
            await ac.post("/api/auth/login", json={"username": "admin", "password": "lels1234"})
            resp = await ac.get("/api/conversations?limit=0")
            assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_clear_conversations_unauthenticated(self, client):
        resp = await client.delete("/api/conversations")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_clear_conversations_success(self, auth_client):
        with patch("main.clear_history", new_callable=AsyncMock) as mock_clear:
            resp = await auth_client.delete("/api/conversations")
            assert resp.status_code == 200
            assert resp.json()["cleared"] is True
            mock_clear.assert_called_once_with("admin")

    @pytest.mark.asyncio
    async def test_trigger_summarize_unauthenticated(self, client):
        resp = await client.post("/api/conversations/summarize")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_trigger_summarize_success(self, auth_client):
        with patch("summarizer.generate_summaries", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = [{"period": "daily", "status": "ok"}]
            resp = await auth_client.post("/api/conversations/summarize")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["summarized"]) == 1
            assert data["summarized"][0]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_chat_persists_history(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock) as mock_save:
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    mock_history.return_value = []
                    mock_chat.return_value = ("Hello!", [
                        {"role": "assistant", "content": "Hello!", "tool_calls": None, "tool_call_id": None}
                    ])
                    resp = await auth_client.post("/api/chat", json={
                        "messages": [{"role": "user", "content": "Hi"}]
                    })
                    assert resp.status_code == 200
                    assert mock_save.call_count == 1
                    turns = mock_save.call_args[0][1]
                    assert len(turns) == 2
                    assert turns[0][0] == "user"
                    assert turns[0][1] == "Hi"
                    assert turns[1][0] == "assistant"
                    assert turns[1][1] == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_includes_history(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock):
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    mock_history.return_value = [
                        {"role": "user", "content": "Previous", "tool_calls": None, "tool_call_id": None, "turn_order": 1}
                    ]
                    mock_chat.return_value = ("Response", [])
                    resp = await auth_client.post("/api/chat", json={
                        "messages": [{"role": "user", "content": "Current"}]
                    })
                    assert resp.status_code == 200
                    messages_arg = mock_chat.call_args[0][0]
                    assert len(messages_arg) == 3
                    assert messages_arg[0]["role"] == "system"
                    assert "Qwelio" in messages_arg[0]["content"]
                    assert messages_arg[1]["content"].startswith("[")
                    assert "Previous" in messages_arg[1]["content"]
                    assert messages_arg[2]["content"].startswith("[")
                    assert "Current" in messages_arg[2]["content"]

    @pytest.mark.asyncio
    async def test_chat_system_prompt_contains_calendar_events(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock):
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    with patch("main.get_service"):
                        with patch("main.get_today_events") as mock_today:
                            with patch("main.list_events") as mock_week:
                                mock_history.return_value = []
                                mock_today.return_value = [{"summary": "Dentist", "start": "09:00", "end": "10:00"}]
                                mock_week.return_value = [{"summary": "Sprint", "start": "2025-06-20T10:00:00", "end": "2025-06-20T11:00:00"}]
                                mock_chat.return_value = ("OK", [])
                                resp = await auth_client.post("/api/chat", json={
                                    "messages": [{"role": "user", "content": "hi"}]
                                })
                                assert resp.status_code == 200
                                sys_msg = mock_chat.call_args[0][0][0]
                                assert sys_msg["role"] == "system"
                                assert "Dentist" in sys_msg["content"]
                                assert "Sprint" in sys_msg["content"]
                                assert "Calendar access: available" in sys_msg["content"]

    @pytest.mark.asyncio
    async def test_chat_calendar_unavailable_in_prompt(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock):
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    with patch("main.get_service", side_effect=Exception("API error")):
                        mock_history.return_value = []
                        mock_chat.return_value = ("OK", [])
                        resp = await auth_client.post("/api/chat", json={
                            "messages": [{"role": "user", "content": "hi"}]
                        })
                        assert resp.status_code == 200
                        sys_msg = mock_chat.call_args[0][0][0]
                        assert sys_msg["role"] == "system"
                        assert "Calendar access: unavailable" in sys_msg["content"]

    @pytest.mark.asyncio
    async def test_chat_turn_order_increments(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock) as mock_save:
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    mock_history.return_value = []
                    mock_chat.return_value = ("Reply", [
                        {"role": "assistant", "content": "Reply", "tool_calls": None, "tool_call_id": None}
                    ])
                    resp = await auth_client.post("/api/chat", json={
                        "messages": [
                            {"role": "user", "content": "Msg1"},
                            {"role": "user", "content": "Msg2"},
                        ]
                    })
                    assert resp.status_code == 200
                    turns = mock_save.call_args[0][1]
                    assert len(turns) == 3
                    assert turns[0][0] == "user"
                    assert turns[1][0] == "user"
                    assert turns[2][0] == "assistant"

    @pytest.mark.asyncio
    async def test_chat_persists_tool_calls(self, auth_client):
        with patch("main.get_history", new_callable=AsyncMock) as mock_history:
            with patch("main.save_turns", new_callable=AsyncMock) as mock_save:
                with patch("main.chat_with_tools", new_callable=AsyncMock) as mock_chat:
                    mock_history.return_value = []
                    tool_call_data = [{"function": {"name": "create_event", "arguments": "{}"}}]
                    mock_chat.return_value = ("Done!", [
                        {"role": "assistant", "content": None, "tool_calls": tool_call_data, "tool_call_id": None},
                        {"role": "tool", "content": "Created", "tool_calls": None, "tool_call_id": "call-1"},
                        {"role": "assistant", "content": "Done!", "tool_calls": None, "tool_call_id": None},
                    ])
                    resp = await auth_client.post("/api/chat", json={
                        "messages": [{"role": "user", "content": "Create event"}]
                    })
                    assert resp.status_code == 200
                    turns = mock_save.call_args[0][1]
                    assert len(turns) == 4
                    assert turns[1][0] == "assistant"
                    assert turns[1][2] == tool_call_data
                    assert turns[2][0] == "tool"
                    assert turns[2][3] == "call-1"

    @pytest.mark.asyncio
    async def test_summarize_cooldown_error(self, auth_client):
        with patch("summarizer.generate_summaries", new_callable=AsyncMock) as mock_gen:
            from llm import LLMError
            mock_gen.side_effect = LLMError("cooldown")
            resp = await auth_client.post("/api/conversations/summarize")
            assert resp.status_code == 200
            assert resp.json()["error"] == "cooldown"

    @pytest.mark.asyncio
    async def test_gcalendar_imports_parse_tz_offset(self):
        """Verify gcalendar can import _parse_tz_offset from prompt (no NameError)."""
        from gcalendar import _parse_tz_offset
        assert _parse_tz_offset("UTC-3") == -3
        assert _parse_tz_offset("UTC+5") == 5
        assert _parse_tz_offset("UTC+0") == 0

    @pytest.mark.asyncio
    async def test_create_event_with_tz_no_name_error(self, auth_client):
        """Verify create_event doesn't raise NameError for _parse_tz_offset."""
        with patch("main.get_service") as mock_get_service:
            mock_service = MagicMock()
            mock_events = MagicMock()
            mock_service.events.return_value = mock_events
            mock_events.list.return_value.execute.return_value = {"items": []}
            mock_events.insert.return_value.execute.return_value = {
                "id": "test-event-1", "summary": "Team Meeting",
                "start": {"dateTime": "2025-07-01T10:00:00-03:00"},
                "end": {"dateTime": "2025-07-01T11:00:00-03:00"}
            }
            mock_get_service.return_value = mock_service
            resp = await auth_client.post("/api/calendar/events", json={
                "summary": "Team Meeting",
                "start": "2025-07-01T10:00:00",
                "end": "2025-07-01T11:00:00"
            })
            assert resp.status_code == 201
            data = resp.json()
            assert data["id"] == "test-event-1"
