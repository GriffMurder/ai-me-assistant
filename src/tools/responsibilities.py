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

# Sacrament prep cycle: Wesley's turn every 3rd month
_PREP_MONTHS = [1, 4, 7, 10]  # Jan, Apr, Jul, Oct


def _next_sacrament_prep() -> str:
    now = datetime.now(ZoneInfo("America/Chicago"))
    for m in _PREP_MONTHS:
        if m > now.month:
            return datetime(now.year, m, 1).strftime("%B %Y")
    return datetime(now.year + 1, _PREP_MONTHS[0], 1).strftime("%B %Y")


def _week_range() -> str:
    now = datetime.now(ZoneInfo("America/Chicago"))
    monday = now - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.strftime('%b %d')} – {sunday.strftime('%b %d, %Y')}"


@tool
def get_my_responsibilities(persona: str = "all"):
    """Get Wesley's current responsibilities and status. Always call this first for any responsibilities or priorities question."""
    now = datetime.now(ZoneInfo("America/Chicago"))
    next_sac = _next_sacrament_prep()
    week = _week_range()

    return f"""RESPONSIBILITIES — {now.strftime("%A, %B %d, %Y")} (Week: {week})

CHURCH (Branch President — Batesville):
• Interviews: Lagging — schedule at least 2 this week (priority #1)
• Sacrament prep: Next turn = {next_sac}
• Ministering: Follow up with at least 3 families this week
• Meetings: Sunday after 12pm preferred. Avoid Wednesday if possible.

PERSONAL:
• 4 kids — protect dedicated family time (HIGH priority)

WORK:
• Accounting / QuickBooks / Stripe (handle via TaskBullet)

This week focus: Interviews → Ministering → Family Time"""


@tool
def log_interview(member_name: str, type_of_interview: str, notes: str = ""):
    """Log a completed worthiness interview for a branch member."""
    details = f"{type_of_interview}. {notes}".strip(". ") if notes else type_of_interview
    try:
        _supabase.table("responsibilities_logs").insert({
            "type": "interview",
            "target": member_name,
            "details": details,
        }).execute()
    except Exception as e:
        return f"❌ Failed to log interview: {e}"
    return f"✅ Interview logged for {member_name} ({type_of_interview}) on {datetime.now(ZoneInfo('America/Chicago')).strftime('%b %d')}"


@tool
def log_ministering(family: str, action_taken: str):
    """Log a ministering follow-up action for a family."""
    try:
        _supabase.table("responsibilities_logs").insert({
            "type": "ministering",
            "target": family,
            "details": action_taken,
        }).execute()
    except Exception as e:
        return f"❌ Failed to log ministering: {e}"
    return f"✅ Ministering logged for {family}: {action_taken}"


@tool
def protect_family_time(reason: str):
    """Flag that family time needs protection this week and record the reason."""
    return f"Family time protected: {reason}"


@tool
def suggest_family_time() -> str:
    """Suggest specific, protected family time activities for this week based on the current date and season."""
    now = datetime.now(ZoneInfo("America/Chicago"))
    dow = now.weekday()  # 0=Mon, 6=Sun
    month = now.month
    hour = now.hour

    # Season
    if month in (12, 1, 2):
        season = "winter"
    elif month in (3, 4, 5):
        season = "spring"
    elif month in (6, 7, 8):
        season = "summer"
    else:
        season = "fall"

    season_activities = {
        "winter": ["board game night", "movie night with homemade popcorn", "baking cookies together"],
        "spring": ["evening bike ride", "backyard catch or frisbee", "plant something in the garden"],
        "summer": ["pool or splash pad afternoon", "backyard cookout + s'mores", "late evening walk"],
        "fall": ["rake leaves (make it a game)", "apple picking or pumpkin patch", "football in the yard"],
    }

    weekday_activities = [
        "30-min one-on-one with one kid — their choice of activity",
        "Eat dinner together, phones down, each person shares their day highlight",
        "Help with homework, then 20 minutes of something fun after",
    ]

    suggestions = []

    if dow >= 5:  # Weekend
        suggestions.extend(season_activities[season][:2])
        suggestions.append("Full Saturday morning — no screens, no work. Pancakes and something outside.")
    else:  # Weekday
        suggestions.extend(weekday_activities[:2])
        suggestions.append(season_activities[season][0])

    lines = "\n".join(f"  • {s}" for s in suggestions)
    day_type = "weekend" if dow >= 5 else "weekday"

    return (
        f"FAMILY TIME — {now.strftime('%A, %B %d')} ({season}, {day_type})\n\n"
        f"{lines}\n\n"
        "→ Lock these in: call create_calendar_event so they don't get bumped."
    )
