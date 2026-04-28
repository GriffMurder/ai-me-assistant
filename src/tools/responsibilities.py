from datetime import datetime

from langchain_core.tools import tool


@tool
def get_my_responsibilities(persona: str = "all"):
    """ALWAYS use this when Wesley asks about responsibilities or what needs attention."""
    return """CURRENT RESPONSIBILITIES (Wesley-specific):

CHURCH (Branch President):
• Interviews: Lagging — schedule at least 2 this week
• Sacrament Prep: Next turn = July
• Ministering: Follow-up needed on at least 3 families
• Meetings: Sunday after 12pm preferred

PERSONAL:
• 4 kids — protect dedicated family time (HIGH priority)

WORK:
• Accounting / QuickBooks flow pending

This Week Priority: Interviews + Ministering + Family Time"""


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
