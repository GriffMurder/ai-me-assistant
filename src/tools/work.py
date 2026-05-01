from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool


@tool
def get_work_priorities() -> str:
    """Get current work / accounting priorities based on today's date.

    Returns date-aware QuickBooks, payroll, and tax reminders so you know
    exactly what accounting actions need attention this week.
    """
    now = datetime.now(ZoneInfo("America/Chicago"))
    day = now.day
    month = now.month
    month_name = now.strftime("%B")
    year = now.year

    actions = []

    # Month-end close window
    if 1 <= day <= 5:
        actions.append(f"📒 Month-end close — reconcile {now.replace(month=month - 1 if month > 1 else 12).strftime('%B')} in QuickBooks now")

    # Payroll prep (early month)
    if 8 <= day <= 14:
        actions.append("💸 Payroll window — verify hours and run payroll in QBO by the 15th")

    # End-of-month payroll prep (for month-start payroll)
    if 25 <= day <= 31:
        actions.append("📋 Gather hours now — payroll runs on the 1st, don't wait")

    # Quarterly estimated taxes (last 2 weeks of Mar, Jun, Sep, Dec)
    quarterly_months = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
    if month in quarterly_months and day >= 15:
        quarter = quarterly_months[month]
        actions.append(
            f"🧾 Estimated taxes due end of {month_name} — review {quarter} profit YTD in QBO and pay if owed"
        )

    # Annual tax prep (Jan/Feb)
    if month == 1:
        actions.append("📊 Year-end — gather W-2s, 1099s, and review {year - 1} books in QBO")
    if month == 2:
        actions.append("📊 Tax season — finalize books and file or schedule CPA time")

    # Always-on context
    actions.append("⚙️  TaskBullet — review open accounting tasks and close anything past-due")

    if not actions:
        actions.append("✅ No urgent accounting deadlines this week — good window to categorize transactions and reconcile")

    lines = "\n".join(f"  {a}" for a in actions)
    return (
        f"WORK PRIORITIES — {now.strftime('%A, %B %d, %Y')}\n\n"
        f"{lines}\n\n"
        "Rule: accounting pain compounds. Do it now."
    )
