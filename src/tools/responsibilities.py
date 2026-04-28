from datetime import datetime

from langchain_core.tools import tool


@tool
def get_my_responsibilities(persona: str = "all"):
    """Get Wesley's current responsibilities with specific this-week actions."""
    today = datetime.now()

    church_status = {
        "interviews": "Lagging — schedule at least 2 this week",
        "sacrament": "Next prep month: July (you last did April)",
        "ministering": "Follow up with at least 3 families this week",
        "meetings": "Sunday after 12pm is best. Avoid Wednesday if possible.",
    }

    if persona.lower() == "church":
        return f"CHURCH STATUS (as of {today.strftime('%b %d')}):\n{church_status}"
    elif persona.lower() == "personal":
        return "PERSONAL: 4 kids - protect dedicated family time this week (HIGH priority)"
    elif persona.lower() == "work":
        return "WORK: Accounting/QuickBooks/Stripe workflow pending (TaskBullet)"
    else:
        return f"""FULL STATUS (as of {today.strftime('%b %d')}):
Church: Interviews lagging + ministering follow-up needed
Personal: Spend more time with the 4 kids (HIGH priority)
Work: Accounting/QuickBooks pending"""


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
