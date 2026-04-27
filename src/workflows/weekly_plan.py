"""Weekly Planning Workflow for AI Me.

Generates a Sunday-night planning summary by analyzing:
- Next week's calendar events
- Unread emails
- Current priorities

Runs as a LangGraph subgraph, triggered from /plan/weekly endpoint.
"""

import datetime
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.prebuilt import create_react_agent

from langgraph.checkpoint.memory import MemorySaver
from src.tools.calendar import get_schedule
from src.tools.email import search_emails
from src.agent import get_llm


# Custom tool to analyze week ahead
@tool
def analyze_week_ahead() -> str:
    """Get calendar events for the next 7 days."""
    today = datetime.date.today()
    next_week = today + datetime.timedelta(days=7)
    return get_schedule.func(
        query="",
        start_date=today.isoformat(),
        end_date=next_week.isoformat()
    )


@tool
def analyze_unread_emails() -> str:
    """Get summary of unread emails."""
    return search_emails.func(query="is:unread", max_results=20)


def build_weekly_planner():
    """Build the weekly planning agent subgraph."""
    llm = get_llm("grok")

    tools = [analyze_week_ahead, analyze_unread_emails]

    system_prompt = """You are Wesley's Weekly Planning Assistant.

    Your job is to create a practical, actionable Sunday-night planning summary that helps Wesley:
    - Review the week ahead (calendar events)
    - Triage unread emails (prioritize urgent ones)
    - Identify potential conflicts or opportunities
    - Suggest preparation steps
    - Flag anything that needs immediate attention

    Style: Direct, practical, protective of Wesley's time. No fluff. Be slightly sarcastic when appropriate.

    Structure your response as:
    1. **Week Ahead Summary** - Key calendar events
    2. **Email Triage** - Urgent items, follow-ups needed
    3. **Potential Conflicts** - Double-bookings, prep needed
    4. **Action Items** - What to do tonight/Monday morning
    5. **Time Protection** - Any boundaries to set

    Keep it concise but comprehensive."""

    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=system_prompt,
        # checkpointer=MemorySaver(),  # No checkpointer for one-off workflow
        name="weekly_planner"
    )


weekly_planner = build_weekly_planner()


def generate_weekly_plan() -> str:
    """Run the weekly planning workflow."""
    result = weekly_planner.invoke({
        "messages": [HumanMessage(content="Generate my Sunday night planning summary for the week ahead.")]
    })
    return result["messages"][-1].content
