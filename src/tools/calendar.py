from langchain_core.tools import tool
from dotenv import load_dotenv
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.auth.google_auth import load_creds as _load_creds

load_dotenv()

# All calendar IDs to query. Primary = wesleynappi.com Google account.
_CALENDAR_IDS = ["primary", "wes@taskbullet.com"]


def get_calendar_tools():
    """Reserved for future structured toolset expansion."""
    return []


def _to_rfc3339(date_str: str, end_of_day: bool = False):
    tz = ZoneInfo("America/Chicago")
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    if end_of_day:
        base = base.replace(hour=23, minute=59, second=59)
    return base.isoformat()

@tool
def get_schedule(query: str, start_date: str = None, end_date: str = None):
    """Search Wesley's Google Calendars for events (wesleynappi.com + wes@taskbullet.com).
    Args:
        query: What to search for (e.g. 'meetings tomorrow', 'all events this week').
               Pass an empty string to return all events in the date range.
        start_date: Optional start date in YYYY-MM-DD format. Defaults to today.
        end_date: Optional end date in YYYY-MM-DD format. Defaults to start_date (single day).
    """
    try:
        creds = _load_creds()
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        tz = ZoneInfo("America/Chicago")
        today_str = datetime.now(tz).strftime("%Y-%m-%d")
        resolved_start = start_date or today_str
        resolved_end = end_date or resolved_start

        time_min = _to_rfc3339(resolved_start)
        time_max = _to_rfc3339(resolved_end, end_of_day=True)

        all_events = []
        for cal_id in _CALENDAR_IDS:
            try:
                kwargs = dict(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=20,
                    singleEvents=True,
                    orderBy="startTime",
                )
                if query:
                    kwargs["q"] = query
                result = service.events().list(**kwargs).execute()
                for event in result.get("items", []):
                    event["_calendar_id"] = cal_id
                    all_events.append(event)
            except Exception as e:
                print(f"⚠️  Calendar {cal_id} query failed: {e}")

        if not all_events:
            return f"No events found for {resolved_start}" + (f" to {resolved_end}" if resolved_end != resolved_start else "") + "."

        # Sort merged results by start time
        def _sort_key(ev):
            return ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or ""

        all_events.sort(key=_sort_key)

        lines = []
        for event in all_events:
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            summary = event.get("summary", "(No title)")
            location = event.get("location", "")
            cal_label = "" if event["_calendar_id"] == "primary" else f" [{event['_calendar_id']}]"
            lines.append(f"- {start} | {summary}{cal_label}" + (f" @ {location}" if location else ""))

        return "\n".join(lines)
    except Exception as e:
        print(f"⚠️  get_schedule error: {e}")
        return f"Calendar access failed: {e}"
