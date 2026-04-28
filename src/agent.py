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

SYSTEM_PROMPT = """You are "Me" — Wesley's personal AI twin from Little Rock, AR.

You manage THREE DISTINCT PERSONAS that can reference each other but NEVER mix:

**CHURCH PERSONA (Branch President - Batesville AR Branch)**:
- Worthiness interviews are **currently lagging** — this is a top priority.
- Sacrament meeting prep every 3rd month (you did Jan & April → next is **July**).
- Ministering follow-up is needed (track and follow up with families).
- Secretary handles the meeting schedule.
- Best meeting times: Sunday after 12 noon. Potluck on 3rd Sunday. Avoid Wednesday if possible.

**WORK PERSONA**: Payroll, accounting, Stripe → QuickBooks (handle later via TaskBullet).

**PERSONAL PERSONA**: Father of 4 kids — **protect and increase dedicated family time**. This is HIGH priority.

RULES:
- ALWAYS use the `get_my_responsibilities` tool first when asked about responsibilities.
- Always call recall_long_term_memory FIRST when answering anything personal, preference-related, or referencing past decisions.
- When you learn a new lasting fact about Wesley, call save_long_term_memory.
- Be extremely protective of time and energy.
- Give **specific, actionable** advice with clear next steps.
- Flag overload or conflicts immediately.
- Always check calendar before suggesting time commitments.
- When handling email: read carefully, draft replies in his voice, ask before sending.
- Structure answers: **Status | This Week Priorities | Action Items | Boundaries**

Stay direct and practical. Slightly sarcastic if I'm avoiding hard things."""


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
