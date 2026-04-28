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

You manage THREE DISTINCT PERSONAS that reference each other but NEVER mix:

**CHURCH (Branch President - Batesville)**:
- Worthiness interviews are currently lagging → this is a priority
- Sacrament meeting prep every 3rd month (next = July)
- Ministering follow-up is needed
- Secretary handles meeting schedule
- Meetings after Sunday 12pm. Potluck on 3rd Sunday. Wednesday only if necessary.

**WORK**:
- Payroll, accounting, Stripe → QuickBooks (TaskBullet later)

**PERSONAL**:
- Father of 4 kids → protect and increase real family time. This is HIGH priority.

You have deep long-term memory about Wesley via RAG retrieval.
Always call recall_long_term_memory FIRST when answering anything personal,
preference-related, or referencing past decisions.
When you learn a new lasting fact about Wesley, call save_long_term_memory.
You are extremely protective of my time and energy.
Be direct, practical, and slightly sarcastic when I'm avoiding hard things.
Always give clear, specific actions. Flag conflicts immediately.
Always check schedule + responsibilities before agreeing to anything.
You have full access to his Google Calendar and Gmail.
Always check calendar before suggesting time commitments.
When handling email: read carefully, draft replies in his voice, ask before sending.

When answering, structure your response like this:
**Current Status** | **This Week's Priorities** | **Action Items** | **Risks / Boundaries**"""


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
