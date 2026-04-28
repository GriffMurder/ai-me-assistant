from langchain_xai import ChatXAI
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

from src.memory.supabase_memory import get_checkpointer
from src.memory.rag_memory import retrieve_relevant_memory, add_to_memory
from src.tools.calendar import get_schedule
from src.tools.email import search_emails, get_email_content, create_draft, apply_triaged_label, list_drafts
from src.tools.responsibilities import get_my_responsibilities, log_interview, log_ministering, protect_family_time

load_dotenv()

SYSTEM_PROMPT = """You are "Me" — Wesley's personal AI twin from Little Rock. Speak like Wesley: direct, practical, no fluff, get to the point fast. Slightly sarcastic only when helpful.

You manage 3 personas that reference each other but never mix:

**CHURCH (Branch President — Batesville)**:
- Interviews lagging → top priority
- Ministering follow-up needed
- Meetings: Sunday after 12pm. Avoid Wednesday if possible.

**WORK**: Accounting/QuickBooks pain (TaskBullet later)

**PERSONAL**: 4 kids — protect family time (HIGH priority)

Rules:
- Always call get_my_responsibilities first for any responsibilities or priorities question.
- Keep replies short and actionable.
- Use this structure for priority questions: **Status | This Week Priorities | Actions | Risks**
- Be protective of time and energy. Flag real problems.
- If a tool returns an error, note it in one sentence and continue with what you know."""


@tool
def recall_long_term_memory(query: str) -> str:
    """Search Wesley's long-term personal memory for relevant past info, preferences, and decisions."""
    return retrieve_relevant_memory(query)


@tool
def save_long_term_memory(fact: str) -> str:
    """Save an important lasting fact about Wesley to long-term memory (preferences, decisions, people, projects)."""
    add_to_memory(fact, metadata={"source": "agent_save"})
    return f"Saved: {fact}"


def get_llm(model: str = "grok"):
    if model == "claude":
        return ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0.3)
    return ChatXAI(model="grok-4", temperature=0.3)


_me_agent = None


def build_me_agent():
    llm = get_llm("grok")
    tools = [
        get_schedule,
        search_emails,
        get_email_content,
        create_draft,
        apply_triaged_label,
        list_drafts,
        get_my_responsibilities,
        log_interview,
        log_ministering,
        protect_family_time,
        recall_long_term_memory,
        save_long_term_memory,
    ]

    return create_react_agent(
        llm,
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


def get_me_agent():
    global _me_agent
    if _me_agent is None:
        _me_agent = build_me_agent()
    return _me_agent
