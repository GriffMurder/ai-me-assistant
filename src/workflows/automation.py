from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import os

from src.agent import get_me_agent
from src.tools.sms import send_sms
from src.workflows.email_automation import proactive_email_triage
from dotenv import load_dotenv

load_dotenv()

scheduler = AsyncIOScheduler()


async def send_morning_briefing():
    """Runs every morning at 7:00 AM CDT — generates and SMS-delivers daily briefing."""
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

    my_phone = os.getenv("MY_PHONE_NUMBER")
    if my_phone:
        send_sms(my_phone, f"🌅 Good morning Wesley\n\n{briefing}")
        print("✅ Morning briefing sent via SMS")
    else:
        print("⚠️ MY_PHONE_NUMBER not set — briefing not delivered")

    return briefing


async def send_weekly_plan():
    """Runs every Sunday at 8:00 PM CDT — generates and SMS-delivers weekly plan."""
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

    my_phone = os.getenv("MY_PHONE_NUMBER")
    if my_phone:
        send_sms(my_phone, f"📅 Weekly Plan\n\n{plan}")
        print("✅ Weekly plan sent via SMS")
    else:
        print("⚠️ MY_PHONE_NUMBER not set — weekly plan not delivered")

    return plan


async def email_triage_job():
    """Scheduled email triage — only runs during daytime hours (8am–8pm CT)."""
    from zoneinfo import ZoneInfo
    now_ct = datetime.now(ZoneInfo("America/Chicago"))
    if not (8 <= now_ct.hour < 20):
        print(f"📧 Email triage skipped (outside daytime window, {now_ct.strftime('%H:%M CT')})")
        return
    try:
        await proactive_email_triage()
    except Exception as e:
        print(f"❌ Scheduled email triage error: {e}")


def start_scheduler():
    """Start all background jobs"""

    # Daily morning briefing at 7:00 AM CDT
    scheduler.add_job(
        send_morning_briefing,
        CronTrigger(hour=7, minute=0, timezone="America/Chicago"),
        id="morning_briefing",
        replace_existing=True,
    )

    # Sunday night weekly plan at 8:00 PM CDT
    scheduler.add_job(
        send_weekly_plan,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="America/Chicago"),
        id="weekly_planning",
        replace_existing=True,
    )

    # Proactive email triage every 6 hours (daytime CT gating inside job)
    scheduler.add_job(
        email_triage_job,
        IntervalTrigger(hours=6),
        id="email_triage",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    print("⏰ Automation scheduler started with SMS delivery!")
