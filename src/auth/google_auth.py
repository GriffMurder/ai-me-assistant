"""Shared Google OAuth: load/save token from Supabase (survives Render redeploys)
with local file fallback for dev. Auto-refreshes expired access tokens.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from supabase import create_client

load_dotenv()

# All scopes the app needs. Single source of truth.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/documents.readonly",
]

TOKEN_FILE = Path("token.json")
_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    _supabase = create_client(url, key)
    return _supabase


def _load_token_dict():
    """Load token JSON dict from Supabase (preferred) or local file."""
    sb = _get_supabase()
    if sb is not None:
        try:
            resp = sb.table("google_token").select("token_json").eq("id", 1).execute()
            rows = resp.data or []
            if rows:
                return json.loads(rows[0]["token_json"])
        except Exception as e:
            print(f"⚠️  Supabase google_token read failed: {e}")
    # Fallback: local file (dev)
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _save_token_dict(data: dict):
    """Persist token JSON dict to Supabase + local file."""
    payload = json.dumps(data)
    sb = _get_supabase()
    if sb is not None:
        try:
            sb.table("google_token").upsert({"id": 1, "token_json": payload}).execute()
        except Exception as e:
            print(f"⚠️  Supabase google_token write failed: {e}")
    try:
        TOKEN_FILE.write_text(payload)
    except Exception:
        pass


def load_creds() -> Credentials:
    """Load credentials, refreshing access token if needed. Raises if no token stored."""
    data = _load_token_dict()
    if not data:
        raise RuntimeError(
            "No Google token stored. Visit /auth/google to authorize."
        )
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token_dict(json.loads(creds.to_json()))
    return creds


def has_token() -> bool:
    return _load_token_dict() is not None


def _client_config():
    """Build OAuth client config from env vars. Required for Web app flow."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars are required."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }
    }


def build_flow(redirect_uri: str) -> Flow:
    return Flow.from_client_config(
        _client_config(),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


def save_creds_from_flow(flow: Flow):
    """After flow.fetch_token(...), persist the credentials."""
    creds = flow.credentials
    _save_token_dict(json.loads(creds.to_json()))
