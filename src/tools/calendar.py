from langchain_core.tools import tool
from dotenv import load_dotenv
from googleapiclient.discovery import build
from datetime import datetime
from zoneinfo import ZoneInfo
import time

from src.auth.google_auth import load_creds as _load_creds

load_dotenv()

# Fallback calendar IDs if dynamic discovery fails.
_FALLBACK_CALENDAR_IDS = ["primary", "wes@taskbullet.com"]

# Module-level discovery cache: (calendar_id_list, fetched_at_timestamp)
_calendar_cache: tuple[list[str], float] | None = None
_CACHE_TTL_SECONDS = 3600  # re-discover every hour


def get_calendar_tools():
    """Reserved for future structured toolset expansion."""
    return []


def _to_rfc3339(date_str: str, end_of_day: bool = False) -> str:
    tz = ZoneInfo("America/Chicago")
    base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
    if end_of_day:
        base = base.replace(hour=23, minute=59, second=59)
    return base.isoformat()


def _discover_calendar_ids(service) -> list[str]:
    """Return all calendar IDs the user has selected (shown) in their Google Calendar UI.

    Uses calendarList.list() and filters to selected=True so we pick up every
    calendar Wesley has ticked on — Family, work, shared, etc. — without pulling
    in hidden/declined noise calendars.

    Falls back to _FALLBACK_CALENDAR_IDS if the API call fails.
    """
    global _calendar_cache

    now = time.monotonic()
    if _calendar_cache is not None:
        ids, fetched_at = _calendar_cache
        if now - fetched_at < _CACHE_TTL_SECONDS:
            return ids

    try:
        result = service.calendarList().list(showHidden=False).execute()
        items = result.get("items", [])
        ids = [
            item["id"]
            for item in items
            if item.get("selected", True)  # most calendars don't set this; default to include
        ]
        if not ids:
            ids = _FALLBACK_CALENDAR_IDS[:]
        _calendar_cache = (ids, now)
        print(f"📅 Discovered {len(ids)} calendars: {ids}")
        return ids
    except Exception as e:
        print(f"⚠️  calendarList discovery failed, using fallback: {e}")
        return _FALLBACK_CALENDAR_IDS[:]


def _fetch_events(service, cal_id: str, time_min: str, time_max: str, query: str = "") -> list[dict]:
    """Fetch events from a single calendar. Returns [] on error."""
    try:
        kwargs = dict(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        )
        if query:
            kwargs["q"] = query
        result = service.events().list(**kwargs).execute()
        items = result.get("items", [])
        for ev in items:
            ev["_calendar_id"] = cal_id
        return items
    except Exception as e:
        print(f"⚠️  Calendar {cal_id} query failed: {e}")
        return []


@tool
def get_schedule(query: str, start_date: str = None, end_date: str = None):
    """Fetch Wesley's full schedule across ALL his Google Calendars (Family, work, shared, etc.).

    Args:
        query: Optional keyword to filter events (e.g. 'soccer', 'dentist').
               Pass an empty string (default) to return EVERY event in the date range —
               always use empty string for general "what's on my calendar" questions.
        start_date: Start date in YYYY-MM-DD format. Defaults to today (Central Time).
        end_date: End date in YYYY-MM-DD format. Defaults to start_date (single day query).
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

        calendar_ids = _discover_calendar_ids(service)

        all_events: list[dict] = []
        for cal_id in calendar_ids:
            all_events.extend(_fetch_events(service, cal_id, time_min, time_max, query))

        # If keyword search returned nothing, retry without the keyword so we always
        # surface at least a full-day view (avoids silently empty responses).
        if not all_events and query:
            print(f"⚠️  Keyword search '{query}' returned 0 results — retrying without keyword")
            for cal_id in calendar_ids:
                all_events.extend(_fetch_events(service, cal_id, time_min, time_max, ""))

        # Deduplicate by event id (same event can appear in multiple calendar list entries)
        seen: set[str] = set()
        unique_events: list[dict] = []
        for ev in all_events:
            eid = ev.get("id", "")
            if eid not in seen:
                seen.add(eid)
                unique_events.append(ev)

        if not unique_events:
            date_range = resolved_start if resolved_start == resolved_end else f"{resolved_start} to {resolved_end}"
            return f"No events found for {date_range}."

        # Sort by start time
        unique_events.sort(key=lambda ev: ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or "")

        lines = []
        for ev in unique_events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or "?"
            summary = ev.get("summary", "(No title)")
            location = ev.get("location", "")
            cal_id = ev.get("_calendar_id", "")
            # Show calendar label for everything except the primary account
            cal_label = "" if cal_id in ("primary", "wesleynappi@gmail.com") else f" [{cal_id}]"
            lines.append(f"- {start} | {summary}{cal_label}" + (f" @ {location}" if location else ""))

        return "\n".join(lines)

    except Exception as e:
        print(f"⚠️  get_schedule error: {e}")
        return f"Calendar access failed: {e}"
