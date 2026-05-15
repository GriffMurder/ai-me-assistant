"""Google Drive tools — browse and search files/folders."""
from __future__ import annotations

from googleapiclient.discovery import build
from langchain_core.tools import tool

from src.auth.google_auth import DRIVE_READONLY_SCOPE, load_creds as _load_creds

_DRIVE_SCOPES = [DRIVE_READONLY_SCOPE]

_MIME_LABELS = {
    "application/vnd.google-apps.folder": "📁 Folder",
    "application/vnd.google-apps.document": "📄 Google Doc",
    "application/vnd.google-apps.spreadsheet": "📊 Google Sheet",
    "application/vnd.google-apps.presentation": "📑 Google Slides",
    "application/vnd.google-apps.form": "📋 Google Form",
    "application/pdf": "📕 PDF",
    "image/jpeg": "🖼 JPEG",
    "image/png": "🖼 PNG",
    "video/mp4": "🎬 MP4 Video",
    "text/plain": "📝 Text",
    "text/csv": "📊 CSV",
}


def _label(mime: str) -> str:
    return _MIME_LABELS.get(mime, f"📎 {mime.split('/')[-1]}")


def _svc():
    return build("drive", "v3", credentials=_load_creds(_DRIVE_SCOPES), cache_discovery=False)


@tool
def search_drive(query: str, limit: int = 20) -> str:
    """Search Wesley's Google Drive for files and folders matching a keyword or phrase.

    Returns name, type, last-modified date, and a direct URL for each match.
    Set limit (1–50) to control how many results come back (default 20).

    Examples:
        search_drive("Straws Soda")
        search_drive("budget 2026", limit=10)
        search_drive("client onboarding template")
    """
    try:
        limit = max(1, min(50, int(limit)))
        svc = _svc()
        # Drive query syntax: https://developers.google.com/drive/api/guides/search-files
        q = f"fullText contains {repr(query)} and trashed = false"
        fields = "files(id, name, mimeType, modifiedTime, webViewLink, parents)"
        results = svc.files().list(
            q=q,
            pageSize=limit,
            fields=fields,
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = results.get("files", [])
        if not files:
            return f'No Drive files found matching "{query}".' 

        lines = [f'🔍 Drive search: "{query}" — {len(files)} result(s)\n']
        for f in files:
            modified = f.get("modifiedTime", "")[:10]
            label = _label(f.get("mimeType", ""))
            name = f.get("name", "(unnamed)")
            url = f.get("webViewLink", "")
            lines.append(f"• {label}: {name}")
            if modified:
                lines[-1] += f"  (modified {modified})"
            if url:
                lines.append(f"  {url}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Drive search failed: {e}"


@tool
def list_drive_folder(folder_id_or_name: str = "root", limit: int = 50) -> str:
    """List the contents of a Google Drive folder.

    Pass "root" (default) to list the top-level My Drive, or supply a folder
    name (the tool will resolve it automatically) or a bare folder ID from a
    Drive URL. Returns name, type, and last-modified date for each item.

    Examples:
        list_drive_folder()                          # My Drive root
        list_drive_folder("TaskBullet")              # find & list a folder by name
        list_drive_folder("1aBcD_folderIdHere")      # list by ID
    """
    try:
        limit = max(1, min(200, int(limit)))
        svc = _svc()

        folder_id = "root"
        display_name = "My Drive"

        raw = folder_id_or_name.strip()

        # If it's not "root" and doesn't look like a bare ID, try to find it by name first
        if raw and raw.lower() != "root":
            # Heuristic: Drive IDs are long alphanumeric strings with underscores/dashes
            looks_like_id = len(raw) > 20 and all(c.isalnum() or c in "-_" for c in raw)
            if looks_like_id:
                folder_id = raw
                display_name = raw
            else:
                # Search for a folder with this name
                q = f"name = {repr(raw)} and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                res = svc.files().list(
                    q=q,
                    pageSize=1,
                    fields="files(id, name)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                found = res.get("files", [])
                if not found:
                    return f'❌ No folder named "{raw}" found in Drive.'
                folder_id = found[0]["id"]
                display_name = found[0]["name"]

        q = f"'{folder_id}' in parents and trashed = false"
        fields = "files(id, name, mimeType, modifiedTime, webViewLink)"
        results = svc.files().list(
            q=q,
            pageSize=limit,
            fields=fields,
            orderBy="folder,name",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = results.get("files", [])

        if not files:
            return f'📁 "{display_name}" is empty.'

        lines = [f"📁 {display_name} — {len(files)} item(s)\n"]
        for f in files:
            modified = f.get("modifiedTime", "")[:10]
            label = _label(f.get("mimeType", ""))
            name = f.get("name", "(unnamed)")
            url = f.get("webViewLink", "")
            entry = f"• {label}: {name}"
            if modified:
                entry += f"  (modified {modified})"
            lines.append(entry)
            if url and f.get("mimeType") != "application/vnd.google-apps.folder":
                lines.append(f"  {url}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Drive folder listing failed: {e}"
