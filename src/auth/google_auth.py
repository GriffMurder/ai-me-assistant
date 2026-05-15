"""Shared Google OAuth: load/save token from Supabase (survives Render redeploys)
with local file fallback for dev. Auto-refreshes expired access tokens.
"""
from collections.abc import Sequence
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from supabase import create_client

load_dotenv()

CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
DOCS_READONLY_SCOPE = "https://www.googleapis.com/auth/documents.readonly"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

CORE_SCOPES = [
    CALENDAR_READONLY_SCOPE,
    CALENDAR_EVENTS_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    GMAIL_COMPOSE_SCOPE,
    GMAIL_MODIFY_SCOPE,
]

OPTIONAL_SCOPES = [
    DOCS_READONLY_SCOPE,
    DRIVE_READONLY_SCOPE,
]

# All scopes the app can request during OAuth.
SCOPES = CORE_SCOPES + OPTIONAL_SCOPES

TOKEN_FILE = Path("token.json")
_supabase = None


def _token_scopes(data: dict) -> set[str]:
    scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(scopes, str):
        return set(scopes.split())
    return set(scopes)


def _resolve_scopes(required_scopes: Sequence[str] | None) -> list[str]:
    scopes = list(required_scopes or CORE_SCOPES)
    return list(dict.fromkeys(scopes))


def missing_scopes(data: dict | None, required_scopes: Sequence[str] | None = None) -> list[str]:
    """Return scopes absent from a stored token, if scope data exists."""
    resolved = _resolve_scopes(required_scopes)
    if not data:
        return resolved
    granted = _token_scopes(data)
    if not granted:
        return []
    return [scope for scope in resolved if scope not in granted]


def missing_required_scopes(data: dict | None) -> list[str]:
    """Return missing core scopes for the main Calendar + Gmail experience."""
    return missing_scopes(data, CORE_SCOPES)


def missing_optional_scopes(data: dict | None) -> list[str]:
    """Return missing non-core scopes such as Drive and Docs."""
    return missing_scopes(data, OPTIONAL_SCOPES)


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


def _save_token_dict(data: dict, *, require_supabase: bool = False) -> dict:
    """Persist token JSON dict and optionally require verified Supabase storage."""
    payload = json.dumps(data)
    sb = _get_supabase()
    status = {
        "saved_to_supabase": False,
        "verified_in_supabase": False,
        "saved_to_file": False,
    }
    supabase_error = None
    if sb is not None:
        try:
            sb.table("google_token").upsert({"id": 1, "token_json": payload}).execute()
            status["saved_to_supabase"] = True
            resp = sb.table("google_token").select("token_json").eq("id", 1).execute()
            rows = resp.data or []
            if not rows:
                raise RuntimeError("read-back returned no rows")
            stored = json.loads(rows[0]["token_json"])
            if _token_scopes(stored) != _token_scopes(data):
                raise RuntimeError("stored scope set does not match saved scope set")
            if data.get("refresh_token") and stored.get("refresh_token") != data.get("refresh_token"):
                raise RuntimeError("stored refresh token does not match saved refresh token")
            status["verified_in_supabase"] = True
        except Exception as e:
            supabase_error = e
            print(f"⚠️  Supabase google_token write failed: {e}")
    elif require_supabase:
        print("⚠️  Supabase not configured — token will be saved to local file only.")
    try:
        TOKEN_FILE.write_text(payload)
        status["saved_to_file"] = True
    except Exception as e:
        if not status["saved_to_supabase"]:
            raise RuntimeError(f"Local token file write failed: {e}") from e
        print(f"⚠️  Local token.json write failed (Supabase is still authoritative): {e}")
    if require_supabase and not status["verified_in_supabase"]:
        reason = supabase_error or "verification did not complete"
        if not status["saved_to_file"]:
            # Nothing persisted anywhere — this is a real failure.
            raise RuntimeError(f"Token could not be persisted (Supabase: {reason}, local file also failed)")
        print(f"⚠️  Supabase verification failed ({reason}). Token saved to local file only — will be lost on next Render redeploy.")
    return status


def load_creds(required_scopes: Sequence[str] | None = None) -> Credentials:
    """Load credentials, refreshing access token if needed.

    By default, require only the core Calendar + Gmail scopes. Feature-specific
    callers can pass narrower or optional scopes.
    """
    data = _load_token_dict()
    if not data:
        raise RuntimeError(
            "No Google token stored. Visit /auth/google to authorize."
        )
    required = _resolve_scopes(required_scopes)
    missing = missing_scopes(data, required)
    if missing:
        raise RuntimeError(
            "Google token is missing required scopes for this feature. Visit /auth/google to re-authorize. "
            f"Missing scopes: {', '.join(missing)}"
        )
    granted = list(_token_scopes(data))
    # Use stored scopes if available so the credential object matches what Google issued.
    # Fall back to all SCOPES (not just required) so no other feature's calls narrow unexpectedly.
    creds = Credentials.from_authorized_user_info(data, granted if granted else SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise RuntimeError(
                "Google token refresh failed. Visit /auth/google to re-authorize. "
                f"Google said: {e}"
            ) from e
        _save_token_dict(json.loads(creds.to_json()))
    return creds


def has_token(required_scopes: Sequence[str] | None = None) -> bool:
    data = _load_token_dict()
    if not data:
        return False
    return not missing_scopes(data, required_scopes)


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


def save_creds_from_flow(flow: Flow, *, require_supabase: bool = False):
    """After flow.fetch_token(...), persist the credentials."""
    creds = flow.credentials
    return _save_token_dict(json.loads(creds.to_json()), require_supabase=require_supabase)
