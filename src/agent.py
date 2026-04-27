from langchain_xai import ChatXAI
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv

from src.memory.supabase_memory import get_checkpointer
from src.tools.calendar import get_schedule
from src.tools.email import search_emails, get_email_content, create_draft

load_dotenv()

SYSTEM_PROMPT = """You are "Me" — Wesley's personal AI twin from Little Rock, AR.
You are extremely protective of my time and energy.
You are direct, practical, and slightly sarcastic when appropriate.
You have full access to my Google Calendar and Gmail.
Always check calendar first before suggesting time commitments.
When handling email: read carefully, draft replies in my natural voice, and ask for approval before sending."""


def get_llm(model: str = "grok"):
    if model == "claude":
        return ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0.3)
    return ChatXAI(model="grok-4", temperature=0.3)


def build_me_agent():
    llm = get_llm("grok")
    tools = [get_schedule, search_emails, get_email_content, create_draft]

    return create_react_agent(
        llm,
        tools,
        prompt=SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


me_agent = build_me_agent()
