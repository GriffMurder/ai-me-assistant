import base64
from email.mime.text import MIMEText

from dotenv import load_dotenv
from googleapiclient.discovery import build
from langchain_core.tools import tool

from src.auth.google_auth import load_creds as _load_creds

load_dotenv()


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


def _get_or_create_label(svc, name: str) -> str:
    """Return the id of a Gmail label, creating it if it doesn't exist."""
    resp = svc.users().labels().list(userId="me").execute()
    for lbl in resp.get("labels", []):
        if lbl["name"].lower() == name.lower():
            return lbl["id"]
    new = svc.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    return new["id"]


@tool
def apply_triaged_label(message_id: str) -> str:
    """Apply the 'AI-Triaged' Gmail label to a message so it is skipped in future triage runs."""
    try:
        svc = _service()
        label_id = _get_or_create_label(svc, "AI-Triaged")
        svc.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        return f"Label 'AI-Triaged' applied to message {message_id}."
    except Exception as e:
        return f"Gmail label error: {e}"


@tool
def list_drafts(max_results: int = 20) -> str:
    """List existing Gmail drafts (id, To, Subject). Use this before create_draft to avoid duplicates."""
    try:
        svc = _service()
        resp = svc.users().drafts().list(userId="me", maxResults=max_results).execute()
        drafts = resp.get("drafts", [])
        if not drafts:
            return "No existing drafts."
        lines = []
        for d in drafts:
            detail = svc.users().drafts().get(
                userId="me", id=d["id"], format="metadata"
            ).execute()
            payload = detail.get("message", {}).get("payload", {})
            lines.append(
                f"- draft_id={d['id']} | To: {_header(payload, 'To')} | Subject: {_header(payload, 'Subject')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Gmail drafts list error: {e}"
