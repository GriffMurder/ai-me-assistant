from langchain_core.tools import tool
from dotenv import load_dotenv
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone

from src.auth.google_auth import load_creds as _load_creds

load_dotenv()


def get_calendar_tools():
    """Reserved for future structured toolset expansion."""
    return []


def _to_rfc3339(date_str: str, end_of_day: bool = False):
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        base = base + timedelta(hours=23, minutes=59, seconds=59)
    return base.isoformat().replace("+00:00", "Z")

@tool
def get_schedule(query: str, start_date: str = None, end_date: str = None):
    """Search Wesley's Google Calendar for events.
    Args:
        query: What to search for (e.g. 'meetings tomorrow', 'all events this week')
        start_date: Optional start date in YYYY-MM-DD format
        end_date: Optional end date in YYYY-MM-DD format
    """
    try:
        creds = _load_creds()
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        now = datetime.now(timezone.utc)
        time_min = _to_rfc3339(start_date) if start_date else now.isoformat().replace("+00:00", "Z")
        time_max = _to_rfc3339(end_date, end_of_day=True) if end_date else None

        events_result = service.events().list(
            calendarId="primary",
            q=query,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])

        if not events:
            return "No matching events found in the selected range."

        lines = []
        for event in events:
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            summary = event.get("summary", "(No title)")
            location = event.get("location", "")
            lines.append(f"- {start} | {summary}" + (f" @ {location}" if location else ""))

        return "\n".join(lines)
    except Exception:
        return "Calendar unavailable right now. Continue without schedule data."
