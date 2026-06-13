# Issue #1: User Authentication (login/logout/session)

## Functional Requirements
- Users must log in before accessing the application
- Login page with username/password fields
- Session persistence across page reloads
- Logout endpoint that invalidates session
- All `/api/*` routes protected except `/api/calendar/auth` and `/api/calendar/callback`
- Login endpoint: `POST /api/auth/login` → returns session cookie

## Current State
- No authentication exists — all endpoints are publicly accessible
- Hardcoded credentials defined: `admin` / `lels1234`
- No login UI in frontend

## Technical Implementation
### Backend (`backend/main.py`)
- Add `POST /api/auth/login` — accepts `{"username": str, "password": str}`, validates against hardcoded credentials, sets session cookie
- Add `POST /api/auth/logout` — clears session cookie
- Add `get_current_user` dependency — FastAPI `Depends()` that checks session cookie, raises `HTTPException(401)` if missing/invalid
- Apply dependency to all `/api/*` routes except auth/callback
- Use `starlette.middleware.sessions.SessionMiddleware` for server-side sessions with signed cookies

### Frontend (`frontend/public/`)
- Add `login.html` — simple login form
- Modify `app.js` — on load, check if session exists via `GET /api/auth/me`; if 401, redirect to login page
- Add logout button in header
- Store no sensitive data in localStorage — session is cookie-based

### Security
- Session cookie: `HttpOnly`, `Secure` (if HTTPS), `SameSite=Strict`
- Session secret: read from `.env` (`SESSION_SECRET`)
- Rate limit login endpoint: max 5 attempts per minute per IP
- No password hashing needed for hardcoded credentials (not production-ready, documented as such)

## Acceptance Criteria
- [ ] Unauthenticated users see login page instead of dashboard
- [ ] `POST /api/auth/login` with correct credentials → 200 + session cookie
- [ ] `POST /api/auth/login` with wrong credentials → 401
- [ ] `GET /api/calendar/today` without session → 401
- [ ] `GET /api/calendar/today` with valid session → 200
- [ ] `POST /api/auth/logout` → clears session, redirects to login
- [ ] Session persists across browser reload
- [ ] Login rate limited to 5 attempts/minute
- [ ] Tests: login success, failure, rate limit, session expiry, protected routes
