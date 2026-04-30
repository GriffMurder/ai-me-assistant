from langchain_core.tools import tool
from googleapiclient.discovery import build
from datetime import datetime, timedelta

from src.auth.google_auth import load_creds as _load_creds

_TIMEZONE = "America/Chicago"
_TIME_FMT = "%Y-%m-%dT%H:%M:%S"


def _parse_and_offset(dt_str: str, offset_hours: int = 0) -> str:
    """Parse an ISO datetime string and return it with an optional hour offset."""
    dt = datetime.strptime(dt_str, _TIME_FMT)
    dt += timedelta(hours=offset_hours)
    return dt.strftime(_TIME_FMT)


@tool
def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str = "",
    description: str = "",
    location: str = "",
    calendar_id: str = "primary",
) -> str:
    """Create a new event on Wesley's Google Calendar.

    Args:
        summary: Event title (required).
        start_time: Start time in ISO format YYYY-MM-DDTHH:MM:SS (e.g. 2026-05-01T09:00:00).
        end_time: End time in same format. Defaults to start_time + 1 hour if omitted.
        description: Optional notes or agenda.
        location: Optional location string.
        calendar_id: Calendar to create the event on. Defaults to 'primary'.
                     Use a calendar email (e.g. 'wes@taskbullet.com') for secondary calendars.
    """
    try:
        resolved_end = end_time.strip() if end_time.strip() else _parse_and_offset(start_time, offset_hours=1)

        event_body = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_time, "timeZone": _TIMEZONE},
            "end": {"dateTime": resolved_end, "timeZone": _TIMEZONE},
        }

        creds = _load_creds()
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        created = service.events().insert(calendarId=calendar_id, body=event_body).execute()

        event_link = created.get("htmlLink", "")
        return f"✅ Event created: '{summary}' on {start_time} → {resolved_end}" + (
            f"\n{event_link}" if event_link else ""
        )
    except Exception as e:
        return f"❌ Failed to create event: {e}"
