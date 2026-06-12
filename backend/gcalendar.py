from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os
import json
import pathlib

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_PATH = pathlib.Path(__file__).parent / ".calendar_token.json"


def _save_token(credentials):
    TOKEN_PATH.write_text(json.dumps({
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }))


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


def _build_flow():
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


def get_service():
    creds = _load_credentials()
    if creds:
        return build("calendar", "v3", credentials=creds)

    flow = _build_flow()
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    auth_url, _ = flow.authorization_url(access_type="consent", prompt="consent")
    return auth_url


def auth_flow(state):
    flow = _build_flow()
    flow.redirect_uri = os.getenv("GOOGLE_REDIRECT_URI")
    flow.fetch_token(authorization_response=state)
    _save_token(flow.credentials)
    return build("calendar", "v3", credentials=flow.credentials)


def list_events(service, days=7):
    now = datetime.now().isoformat()
    end = (datetime.now() + timedelta(days=days)).isoformat()

    events_result = service.events().list(
        calendarId="primary",
        timeMin=now,
        timeMax=end,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    formatted = []
    for e in events:
        start = e.get("start", {})
        formatted.append({
            "summary": e.get("summary", "No title"),
            "start": start.get("dateTime") or start.get("date"),
            "end": e.get("end", {}).get("dateTime"),
            "location": e.get("location"),
            "description": e.get("description"),
        })
    return formatted


def get_today_events(service):
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end = now.replace(hour=23, minute=59, second=59).isoformat()

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start,
        timeMax=end,
        maxResults=50,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    formatted = []
    for e in events:
        start = e.get("start", {})
        formatted.append({
            "summary": e.get("summary", "No title"),
            "start": start.get("dateTime") or start.get("date"),
            "end": e.get("end", {}).get("dateTime"),
            "location": e.get("location"),
            "description": e.get("description"),
        })
    return formatted
