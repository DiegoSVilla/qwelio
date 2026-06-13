from fastapi import HTTPException, Request
from pydantic import BaseModel
from typing import Any
import time
import hmac

HARDCODED_USERS = {
    "admin": "lels1234",
}

SESSION_KEY = "user"


class User(BaseModel):
    id: str
    username: str
    settings: dict[str, Any] = {}


class RateLimiter:
    """Simple in-memory rate limiter keyed by IP address. Only tracks failed attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    def _client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cleanup(self, ip: str, now: float):
        if ip in self._requests:
            self._requests[ip] = [t for t in self._requests[ip] if now - t < self.window_seconds]
            if not self._requests[ip]:
                del self._requests[ip]

    def is_limited(self, request: Request) -> bool:
        ip = self._client_ip(request)
        now = time.time()
        self._cleanup(ip, now)
        if ip not in self._requests:
            self._requests[ip] = []
        if len(self._requests[ip]) >= self.max_attempts:
            return True
        return False

    def record(self, request: Request):
        ip = self._client_ip(request)
        now = time.time()
        self._cleanup(ip, now)
        if ip not in self._requests:
            self._requests[ip] = []
        self._requests[ip].append(now)


_rate_limiter = RateLimiter(max_attempts=5, window_seconds=60)

def reset_rate_limiter():
    _rate_limiter._requests.clear()


def get_current_user(request: Request) -> User:
    user_data = request.session.get(SESSION_KEY)
    if not user_data:
        raise HTTPException(status_code=401, detail="Authentication required")
    return User(**user_data)


def verify_password(username: str, password: str) -> bool:
    stored = HARDCODED_USERS.get(username)
    if not stored:
        stored = ""
    return hmac.compare_digest(stored, password)
