from datetime import datetime

from src.agent import get_me_agent

TRIAGE_PROMPT = """Perform a proactive email triage for Wesley. Follow these steps exactly:

1. Call list_drafts() to see what draft replies already exist.

2. Call search_emails with query 'is:unread -label:AI-Triaged newer_than:2d' and max_results=20.
   If no results: return "No new emails to triage."

3. For each email found, get its content with get_email_content(message_id).

4. Categorize each email as one of:
   - URGENT: needs action today
   - Needs Reply: requires a response within a few days
   - FYI: informational, no action needed
   - Low Priority: newsletters, promos, notifications

5. For every URGENT or Needs Reply email:
   - Check if an existing draft (from step 1) already addresses the same recipient/thread.
   - If NO existing draft: call create_draft(subject, body, to) with a reply written in Wesley's voice.
     Wesley's voice: direct, practical, mildly sarcastic, gets to the point fast, no fluff.
   - If a draft already exists: skip draft creation and note it.

6. After processing EACH email (regardless of category): call apply_triaged_label(message_id).

7. Return a concise triage summary:
   - Counts: X URGENT, X Needs Reply, X FYI, X Low Priority
   - List of new draft ids created and who they're addressed to
   - List of any URGENT items that need Wesley's personal review before sending
   - Any notable items (payments, deadlines, calendar conflicts)

Important constraints:
- NEVER send any email. Drafts only.
- Do not create a draft if one already exists for that thread/recipient.
- Apply AI-Triaged label to every processed message.
"""


async def proactive_email_triage() -> str:
    """Runs on scheduler — triage unread emails, create drafts, apply labels."""
    print(f"📧 Starting Email Triage - {datetime.now()}")
    try:
        result = get_me_agent().invoke(
            {"messages": [{"role": "user", "content": TRIAGE_PROMPT}]},
            config={"configurable": {"thread_id": "email-triage-automation"}},
        )
        report = result["messages"][-1].content
        print(f"📧 Email Triage Complete:\n{report}")
        return report
    except Exception as e:
        msg = f"Email triage failed: {e}"
        print(f"❌ {msg}")
        return msg


async def manual_email_triage() -> str:
    """Manual trigger wrapper — same logic, returns report for API response."""
    return await proactive_email_triage()
