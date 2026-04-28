from datetime import datetime

from langchain_core.tools import tool


@tool
def get_my_responsibilities(persona: str = "all"):
    """Return Wesley's current responsibilities and status across church, work, and personal personas."""
    data = {
        "church": {
            "interviews": "Lagging - needs focus this week",
            "sacrament": "Next prep: July",
            "ministering": "Follow-up required",
            "meetings": "Sunday after 12pm. Secretary manages schedule.",
            "boundaries": "Avoid Wednesday if possible",
        },
        "work": {
            "status": "QuickBooks/Stripe workflow pending (TaskBullet)",
            "priority": "Medium",
        },
        "personal": {
            "status": "4 kids - increase dedicated time",
            "priority": "HIGH",
        },
    }
    return data if persona == "all" else data.get(persona, data)


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
