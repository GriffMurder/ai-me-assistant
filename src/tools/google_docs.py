import re

from googleapiclient.discovery import build
from langchain_core.tools import tool

from src.auth.google_auth import load_creds as _load_creds

_DOC_URL_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")
_MAX_CHARS = 8000


def _extract_doc_id(doc_id_or_url: str) -> str:
    """Accept either a bare document ID or a full docs.google.com URL."""
    m = _DOC_URL_RE.search(doc_id_or_url)
    return m.group(1) if m else doc_id_or_url.strip()


def _doc_to_text(doc: dict) -> str:
    """Walk the document body and extract plain text from all text runs."""
    chunks = []
    for block in doc.get("body", {}).get("content", []):
        para = block.get("paragraph")
        if not para:
            continue
        for elem in para.get("elements", []):
            text_run = elem.get("textRun")
            if text_run:
                chunks.append(text_run.get("content", ""))
    return "".join(chunks)


@tool
def read_google_doc(document_id_or_url: str) -> str:
    """Read the full text of a Google Doc.

    Accepts either a bare document ID (the long string from the URL) or the
    full docs.google.com URL. Returns up to 8,000 characters; longer docs are
    truncated with a note showing total length.

    Example:
        read_google_doc("https://docs.google.com/document/d/1aBcD.../edit")
        read_google_doc("1aBcD...")
    """
    try:
        doc_id = _extract_doc_id(document_id_or_url)
        svc = build("docs", "v1", credentials=_load_creds(), cache_discovery=False)
        doc = svc.documents().get(documentId=doc_id).execute()
        title = doc.get("title", "(untitled)")
        text = _doc_to_text(doc)
        total = len(text)
        truncated = total > _MAX_CHARS
        excerpt = text[:_MAX_CHARS]
        suffix = f"\n\n[Truncated — showing {_MAX_CHARS:,} of {total:,} chars]" if truncated else ""
        return f"📄 {title}\n\n{excerpt}{suffix}"
    except Exception as e:
        return f"❌ Failed to read doc: {e}"
