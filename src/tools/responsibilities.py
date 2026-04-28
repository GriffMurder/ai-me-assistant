from datetime import datetime

from langchain_core.tools import tool


@tool
def get_my_responsibilities(persona: str = "all"):
    """ALWAYS called when asked about responsibilities."""
    return """WESLEY'S CURRENT RESPONSIBILITIES:

CHURCH (Branch President):
• Interviews: Lagging — schedule minimum 2 this week
• Sacrament: July (you did Jan & April)
• Ministering: Follow up with at least 3 families

PERSONAL:
• 4 kids — block real family time (HIGH priority)

WORK:
• Accounting/QuickBooks pending

This week focus: Interviews + Ministering + Family Time"""


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
