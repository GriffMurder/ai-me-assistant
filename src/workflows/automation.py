from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime

from src.agent import get_me_agent
from dotenv import load_dotenv

load_dotenv()

scheduler = AsyncIOScheduler()


async def morning_briefing():
    """Runs every morning — daily AI summary"""
    print(f"🌅 Running Morning Briefing - {datetime.now()}")

    prompt = """Run a full morning briefing for Wesley:
    1. Pull today's schedule
    2. Check unread/high-priority emails
    3. Give 3 top priorities for the day
    4. Any time conflicts or protection advice
    Keep it concise and direct."""

    result = get_me_agent().invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"configurable": {"thread_id": "daily-morning"}}
    )

    briefing = result["messages"][-1].content
    print("📋 Morning Briefing:\n", briefing)
    # TODO: Send via email or Twilio SMS
    return briefing


async def weekly_planning():
    """Runs every Sunday night"""
    print(f"📅 Running Weekly Planning - {datetime.now()}")

    prompt = """Create Wesley's full weekly plan:
    - Pull next 7 days calendar
    - Review recent emails
    - Suggest time blocks for deep work
    - Flag any conflicts
    - Give clear action items for the week"""

    result = get_me_agent().invoke(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"configurable": {"thread_id": "weekly-plan"}}
    )

    plan = result["messages"][-1].content
    print("📅 Weekly Plan Generated:\n", plan)
    return plan


def start_scheduler():
    """Start all background jobs"""

    # Daily morning briefing at 7:00 AM CDT
    scheduler.add_job(
        morning_briefing,
        CronTrigger(hour=7, minute=0, timezone="America/Chicago"),
        id="morning_briefing"
    )

    # Sunday night weekly plan at 8:00 PM CDT
    scheduler.add_job(
        weekly_planning,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="America/Chicago"),
        id="weekly_planning"
    )

    scheduler.start()
    print("⏰ Background automation scheduler started!")
