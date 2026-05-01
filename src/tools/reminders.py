import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langchain_core.tools import tool
from supabase import create_client

load_dotenv()

_supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
)


@tool
def set_reminder(task: str, days: int = 3) -> str:
    """Set a follow-up reminder that will fire an SMS to Wesley in N days.

    Args:
        task: Description of what to follow up on.
        days: Number of days from now (default 3, minimum 1).
    """
    days = max(1, days)
    now_ct = datetime.now(ZoneInfo("America/Chicago"))
    remind_at = (now_ct + timedelta(days=days)).isoformat()
    remind_label = (now_ct + timedelta(days=days)).strftime("%A, %b %d")
    try:
        _supabase.table("reminders").insert({
            "task": task,
            "remind_at": remind_at,
        }).execute()
    except Exception as e:
        return f"❌ Failed to set reminder: {e}"
    return f"✅ Reminder set: '{task}' — fires {remind_label} ({days} day{'s' if days != 1 else ''})"
