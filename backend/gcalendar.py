from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import os
import json
import pathlib

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = pathlib.Path(__file__).parent / ".calendar_token.json"


class NotAuthenticated(Exception):
    def __init__(self, auth_url: str):
        self.auth_url = auth_url
        super().__init__(f"Not authenticated. Visit: {auth_url}")


def _save_token(credentials):
    TOKEN_PATH.write_text(json.dumps({
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }))
    TOKEN_PATH.chmod(0o600)


def _load_credentials():
    if TOKEN_PATH.exists():
        data = json.loads(TOKEN_PATH.read_text())
        creds = Credentials(**data)
        if not creds.valid:
            if creds.refresh_token:
                creds.refresh(Request())
                _save_token(creds)
        return creds
    return None


def _check_env():
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")


def _build_flow():
    _check_env()
    return Flow.from_client_config(
        {
            "web": {
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )


def _format_events(events):
    formatted = []
    for e in events:
        start = e.get("start", {})
        formatted.append({
            "summary": e.get("summary", "No title"),
            "start": start.get("dateTime") or start.get("date"),
            "end": (e.get("end", {}) or {}).get("dateTime") or (e.get("end", {}) or {}).get("date"),
            "location": e.get("location"),
            "description": e.get("description"),
        })
    return formatted


def get_service():
    creds = _load_credentials()
    if creds:
        return build("calendar", "v3", credentials=creds)

    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise NotAuthenticated("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")

    flow = _build_flow()
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    auth_url, _ = flow.authorization_url(access_type="consent", prompt="consent")
    raise NotAuthenticated(auth_url)


def auth_flow(callback_url):
    flow = _build_flow()
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    flow.fetch_token(authorization_response=callback_url)
    _save_token(flow.credentials)
    return build("calendar", "v3", credentials=flow.credentials)


def _fetch_events(service, time_min, time_max):
    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return _format_events(events_result.get("items", []))


def list_events(service, days=7):
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    return _fetch_events(service, now.isoformat(), end.isoformat())


def get_today_events(service):
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return _fetch_events(service, start.isoformat(), end.isoformat())
