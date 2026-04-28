from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

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
    return f"Interview logged: {member_name} ({type_of_interview}) on {datetime.now().strftime('%b %d')}"


@tool
def log_ministering(family: str, action_taken: str):
    """Log a ministering follow-up action for a family."""
    return f"Ministering logged for {family}: {action_taken}"


@tool
def protect_family_time(reason: str):
    """Flag that family time needs protection this week and record the reason."""
    return f"Family time protected: {reason}"
