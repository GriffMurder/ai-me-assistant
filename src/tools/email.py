import base64
import json
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from langchain_core.tools import tool

load_dotenv()

# Scopes we expect token.json to already cover.
# NOTE: drafts.create needs gmail.compose or gmail.modify. Re-auth if you want drafts.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _load_creds():
    token_path = Path("token.json")
    if not token_path.exists():
        raise FileNotFoundError("token.json not found. Complete OAuth first.")

    data = json.loads(token_path.read_text())
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return creds


def _service():
    return build("gmail", "v1", credentials=_load_creds(), cache_discovery=False)


def _header(payload, name):
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(payload):
    if not payload:
        return ""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")
    if data and mime.startswith("text/"):
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        except Exception:
            return ""
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


@tool
def search_emails(query: str, max_results: int = 5):
    """Search Wesley's Gmail inbox.
    Good queries: 'is:unread', 'from:someone@example.com', 'subject:meeting', 'newer_than:2d'.
    Returns a short list of matching messages with id, sender, subject, snippet.
    """
    try:
        svc = _service()
        resp = svc.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = resp.get("messages", [])
        if not messages:
            return "No matching emails."

        lines = []
        for m in messages:
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            payload = msg.get("payload", {})
            lines.append(
                f"- id={msg['id']} | {_header(payload, 'Date')} | "
                f"From: {_header(payload, 'From')} | Subject: {_header(payload, 'Subject')} | "
                f"Snippet: {msg.get('snippet', '')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Gmail search error: {e}"


@tool
def get_email_content(message_id: str):
    """Get the full body and headers of a specific Gmail message by id."""
    try:
        svc = _service()
        msg = svc.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        payload = msg.get("payload", {})
        return (
            f"From: {_header(payload, 'From')}\n"
            f"To: {_header(payload, 'To')}\n"
            f"Date: {_header(payload, 'Date')}\n"
            f"Subject: {_header(payload, 'Subject')}\n\n"
            f"{_extract_body(payload).strip()}"
        )
    except Exception as e:
        return f"Gmail get error: {e}"


@tool
def create_draft(subject: str, body: str, to: str):
    """Create a Gmail draft (does NOT send). Requires gmail.compose or gmail.modify scope."""
    try:
        svc = _service()
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        draft = svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
        return f"Draft created. id={draft.get('id')}"
    except Exception as e:
        return f"Gmail draft error: {e}"
