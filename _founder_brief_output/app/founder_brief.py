"""app/founder_brief.py — Daily Founder Brief for Wesley.

Collects 6 categories of business signals from existing DB tables (no new
migrations), formats them as Slack Block Kit blocks, and posts to the
founder's configured Slack channel or DM.

Schedule: Mon–Fri 8:05 AM CT (via Celery Beat in workers.py)
Debug:    POST /debug/founder-brief/run-once?dry_run=true

Sections
--------
1. Urgent Client Risks      — SLA breaches, at-risk clients, locked budgets
2. Revenue Opportunities    — Low-balance clients, recent purchases, new signups
3. Ops Bottlenecks          — Open tasks, stalled escalations, Clockify sync health
4. Website / Marketing      — Signup trend (7d vs prior 7d), bucket purchase volume
5. Recommended Actions      — Rule-based derivations from the above signals
6. Drafts Needing Approval  — ACS reports in drafted state, open founder interventions
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from sqlalchemy import text

from .config import settings
from .db import SessionLocal
from .slack_blocks import (
    divider as _divider,
    header as _header,
    section as _section,
    context as _context,
)

# Re-use daily data collectors that are already production-tested
from .tb_ops_digest import (
    _fetch_at_risk_clients,
    _fetch_open_manager_escalations,
    _fetch_sla_breaches,
)

logger = logging.getLogger("tb.founder_brief")

SLACK_API = "https://slack.com/api"
_LOW_HOURS_THRESHOLD = 5.0  # hours — flag active buckets below this


# ─── Slack helpers ────────────────────────────────────────────────────────────

def _founder_channel() -> str:
    """Return the Slack channel/user ID to post the brief to."""
    return (
        os.getenv("FOUNDER_BRIEF_CHANNEL_ID")
        or getattr(settings, "FOUNDER_BRIEF_CHANNEL_ID", None)
        or getattr(settings, "FOUNDER_DM_SLACK_USER_ID", None)
        or ""
    ).strip()


def _slack_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _post_message(channel: str, blocks: list[dict], fallback: str) -> dict:
    if not getattr(settings, "SLACK_BOT_TOKEN", None) or not channel:
        return {"ok": False, "error": "missing_token_or_channel"}
    try:
        r = requests.post(
            f"{SLACK_API}/chat.postMessage",
            headers=_slack_headers(),
            json={"channel": channel, "text": fallback, "blocks": blocks},
            timeout=30,
        )
        return r.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ─── Signal collectors ────────────────────────────────────────────────────────

def _collect_client_risks(db) -> dict:
    """SLA breaches, at-risk clients, open escalations, locked budgets."""
    try:
        at_risk = _fetch_at_risk_clients(db, top_n=5)
    except Exception as exc:
        logger.warning("[founder_brief] _fetch_at_risk_clients failed: %s", exc)
        at_risk = []

    try:
        escalations = _fetch_open_manager_escalations(db, sla_hours=48)
    except Exception as exc:
        logger.warning("[founder_brief] _fetch_open_manager_escalations failed: %s", exc)
        escalations = {"total": 0, "oldest_days": None, "sla_breached": 0}

    try:
        sla_breaches = _fetch_sla_breaches(db)
    except Exception as exc:
        logger.warning("[founder_brief] _fetch_sla_breaches failed: %s", exc)
        sla_breaches = []

    try:
        locked = int(db.execute(text("""
            SELECT COUNT(*) AS cnt
            FROM customers
            WHERE hours_locked_at IS NOT NULL AND active = TRUE
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] locked budget query failed: %s", exc)
        locked = None

    try:
        founder_open = int(db.execute(text("""
            SELECT COUNT(*) AS cnt
            FROM interventions
            WHERE level = 'founder' AND status = 'open'
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] founder interventions query failed: %s", exc)
        founder_open = None

    return {
        "at_risk_clients": at_risk,
        "open_manager_escalations": escalations,
        "sla_breaches": sla_breaches,
        "budget_locked_count": locked,
        "founder_interventions_open": founder_open,
    }


def _collect_revenue_signals(db) -> dict:
    """Low-balance buckets, new signups, recent purchases, total active hours."""
    try:
        low_rows = db.execute(text("""
            SELECT c.id, c.name, CAST(b.hours_balance AS FLOAT) AS hours_balance
            FROM buckets b
            JOIN customers c ON c.id = b.customer_id
            WHERE b.status = 'active'
              AND b.hours_balance < :threshold
              AND b.hours_balance >= 0
              AND c.active = TRUE
              AND b.hpp_protected = FALSE
            ORDER BY b.hours_balance ASC
            LIMIT 10
        """), {"threshold": _LOW_HOURS_THRESHOLD}).mappings().all()
        low_balance: list | None = [dict(r) for r in low_rows]
    except Exception as exc:
        logger.warning("[founder_brief] low_balance query failed: %s", exc)
        low_balance = None

    try:
        new_customers_24h = int(db.execute(text("""
            SELECT COUNT(*) FROM customers
            WHERE created_at > NOW() - INTERVAL '24 hours' AND active = TRUE
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] new_customers_24h query failed: %s", exc)
        new_customers_24h = None

    try:
        purchases_7d = int(db.execute(text("""
            SELECT COUNT(*) FROM stripe_events
            WHERE event_type IN ('checkout.session.completed', 'invoice.payment_succeeded')
              AND processed = TRUE
              AND created_at > NOW() - INTERVAL '7 days'
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] purchases_7d query failed: %s", exc)
        purchases_7d = None

    try:
        total_active_hours = float(db.execute(text("""
            SELECT COALESCE(SUM(hours_balance), 0)
            FROM buckets
            WHERE status = 'active'
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] total_active_hours query failed: %s", exc)
        total_active_hours = None

    return {
        "low_balance_clients": low_balance,
        "new_customers_24h": new_customers_24h,
        "purchases_7d": purchases_7d,
        "total_active_hours": total_active_hours,
    }


def _collect_ops_bottlenecks(db) -> dict:
    """Open todos, pending ACS reports, open manager interventions, Clockify sync."""
    try:
        open_todos = int(db.execute(text("""
            SELECT COUNT(*) FROM bc_todos WHERE status = 'open'
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] open_todos query failed: %s", exc)
        open_todos = None

    try:
        acs_drafted = int(db.execute(text("""
            SELECT COUNT(*) FROM task_completion_reports WHERE status = 'drafted'
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] acs_drafted query failed: %s", exc)
        acs_drafted = None

    try:
        open_interventions = int(db.execute(text("""
            SELECT COUNT(*) FROM interventions
            WHERE level = 'manager' AND status = 'open'
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] open_interventions query failed: %s", exc)
        open_interventions = None

    last_clockify_sync = None
    clockify_healthy = None
    try:
        row = db.execute(text("""
            SELECT MAX(synced_at) AS last_synced
            FROM clockify_sync_logs
        """)).mappings().first()
        if row and row["last_synced"]:
            last_clockify_sync = row["last_synced"]
            ts = last_clockify_sync
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
            clockify_healthy = age_min < 30
    except Exception as exc:
        logger.warning("[founder_brief] clockify sync query failed: %s", exc)

    return {
        "open_todos": open_todos,
        "acs_drafted": acs_drafted,
        "open_manager_interventions": open_interventions,
        "last_clockify_sync": last_clockify_sync,
        "clockify_sync_healthy": clockify_healthy,
    }


def _collect_marketing_signals(db) -> dict:
    """New customer signup trend (7d vs prior 7d), purchase volume this week."""
    try:
        signups_7d = int(db.execute(text("""
            SELECT COUNT(*) FROM customers
            WHERE created_at >= NOW() - INTERVAL '7 days' AND active = TRUE
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] signups_7d query failed: %s", exc)
        signups_7d = None

    try:
        signups_prior_7d = int(db.execute(text("""
            SELECT COUNT(*) FROM customers
            WHERE created_at >= NOW() - INTERVAL '14 days'
              AND created_at < NOW() - INTERVAL '7 days'
              AND active = TRUE
        """)).scalar() or 0)
    except Exception as exc:
        logger.warning("[founder_brief] signups_prior_7d query failed: %s", exc)
        signups_prior_7d = None

    try:
        row = db.execute(text("""
            SELECT
                COUNT(*) AS cnt,
                COALESCE(SUM(
                    CASE WHEN (se.payload_summary->>'hours') IS NOT NULL
                         THEN (se.payload_summary->>'hours')::FLOAT
                         ELSE 0 END
                ), 0) AS total_hours
            FROM stripe_events se
            WHERE se.event_type IN (
                'checkout.session.completed',
                'invoice.payment_succeeded'
            )
              AND se.processed = TRUE
              AND se.created_at >= date_trunc('week', NOW())
        """)).mappings().first()
        week_purchases: dict[str, Any] = dict(row) if row else {}
    except Exception as exc:
        logger.warning("[founder_brief] purchases_this_week query failed: %s", exc)
        week_purchases = {}

    return {
        "signups_7d": signups_7d,
        "signups_prior_7d": signups_prior_7d,
        "week_purchases": week_purchases,
    }


def _collect_drafts_pending(db) -> dict:
    """ACS reports awaiting VA approval and open founder-level interventions."""
    try:
        acs_rows = db.execute(text("""
            SELECT tcr.id, tcr.task_type, tcr.created_at, bt.title
            FROM task_completion_reports tcr
            LEFT JOIN basecamp_todos bt ON bt.basecamp_todo_id = tcr.basecamp_thread_id
            WHERE tcr.status = 'drafted'
            ORDER BY tcr.created_at DESC
            LIMIT 10
        """)).mappings().all()
        acs_drafts: list | None = [dict(r) for r in acs_rows]
    except Exception as exc:
        logger.warning("[founder_brief] acs_drafts query failed: %s", exc)
        acs_drafts = None

    try:
        founder_rows = db.execute(text("""
            SELECT iv.id, iv.reason, iv.created_at, c.name AS customer_name
            FROM interventions iv
            LEFT JOIN customers c ON c.id = iv.customer_id
            WHERE iv.level = 'founder' AND iv.status = 'open'
            ORDER BY iv.created_at ASC
            LIMIT 5
        """)).mappings().all()
        founder_pending: list | None = [dict(r) for r in founder_rows]
    except Exception as exc:
        logger.warning("[founder_brief] founder_pending query failed: %s", exc)
        founder_pending = None

    return {
        "acs_drafts": acs_drafts,
        "founder_interventions": founder_pending,
    }


def _build_recommended_actions(data: dict) -> list[str]:
    """Derive prioritized action list from collected signals. Rule-based only."""
    actions: list[str] = []

    sla_br = data.get("client_risks", {}).get("sla_breaches", [])
    if sla_br:
        actions.append(f"🔴 *Resolve {len(sla_br)} SLA breach(es)* — these clients have been waiting too long")

    founder_open = data.get("client_risks", {}).get("founder_interventions_open") or 0
    if int(founder_open) > 0:
        actions.append(f"🚨 *Review {founder_open} escalation(s) awaiting your attention*")

    locked = data.get("client_risks", {}).get("budget_locked_count") or 0
    if int(locked) > 0:
        actions.append(
            f"⏸️ *{locked} client(s) have exhausted their hours* "
            "— VA work may be paused; follow up on renewal"
        )

    low = data.get("revenue", {}).get("low_balance_clients") or []
    if low:
        names = ", ".join(r.get("name", "?") for r in low[:3])
        more = f" + {len(low) - 3} more" if len(low) > 3 else ""
        actions.append(
            f"💡 *Reach out about hour renewal* — {len(low)} client(s) "
            f"below {_LOW_HOURS_THRESHOLD}h: {names}{more}"
        )

    new_24h = data.get("revenue", {}).get("new_customers_24h") or 0
    if int(new_24h) > 0:
        actions.append(f"✅ *{new_24h} new client(s) signed up in the last 24h* — send a welcome check-in")

    if data.get("ops", {}).get("clockify_sync_healthy") is False:
        actions.append("⚠️ *Clockify sync is stale (>30 min)* — check the sync job or trigger a manual sync")

    acs = data.get("ops", {}).get("acs_drafted") or 0
    if int(acs) > 10:
        actions.append(f"📋 *{acs} completion reports in draft* — VAs haven't approved yet; consider nudging")

    if not actions:
        actions.append("✅ No urgent actions — looks clean today")

    return actions


# ─── Block Kit formatter ──────────────────────────────────────────────────────

def _fmt_founder_brief_blocks(data: dict, today_str: str) -> tuple[list[dict], str]:
    """Return (blocks, fallback_text) for the Slack Founder Brief message."""
    blocks: list[dict] = []
    now_utc = datetime.now(timezone.utc)

    blocks.append(_header(f"📋 Founder Brief — {today_str}"))
    blocks.append(_context("Daily business snapshot · for Wesley only · visibility + recommended actions"))

    # ── §1 Urgent Client Risks ───────────────────────────────────────────────
    blocks.append(_divider())
    blocks.append(_section("*§1 — Urgent Client Risks*"))
    risks = data.get("client_risks", {})
    sla_br = risks.get("sla_breaches", [])
    at_risk = risks.get("at_risk_clients", [])
    esc = risks.get("open_manager_escalations", {})
    locked = risks.get("budget_locked_count")
    founder_open = risks.get("founder_interventions_open")

    if sla_br:
        lines = [f"🔥 *{len(sla_br)} SLA Breach(es)*"]
        for b in sla_br[:5]:
            cust = b.get("customer_name") or f"id:{b.get('customer_id', '?')}"
            b_at = b.get("sla_breached_at")
            age_str = ""
            if b_at:
                try:
                    if b_at.tzinfo is None:
                        b_at = b_at.replace(tzinfo=timezone.utc)
                    age_h = (now_utc - b_at).total_seconds() / 3600
                    age_str = f" ({age_h:.0f}h overdue)"
                except Exception:
                    pass
            lines.append(f"• {cust}{age_str}")
        blocks.append(_section("\n".join(lines)))
    else:
        blocks.append(_section("✅ *SLA Breaches* — none"))

    if at_risk:
        ar_lines = [f"🔴 *{len(at_risk)} At-Risk Client(s)*"]
        for c in at_risk[:5]:
            name = c.get("name") or f"id:{c.get('customer_id', '?')}"
            h = c.get("health") or c.get("client_health_score", "?")
            tier = c.get("effective_tier") or "—"
            ar_lines.append(f"• {name} — health {h}  tier {tier}")
        blocks.append(_section("\n".join(ar_lines)))

    if esc:
        total_e = esc.get("total", 0)
        breached_e = esc.get("sla_breached", 0)
        oldest_e = esc.get("oldest_days")
        oldest_str = f", oldest {oldest_e}d" if oldest_e else ""
        breach_str = f" | {breached_e} SLA-breached" if breached_e else ""
        emoji = "🚨" if int(total_e) > 0 else "✅"
        label = f"{total_e} open{oldest_str}{breach_str}" if int(total_e) > 0 else "none open"
        blocks.append(_section(f"{emoji} *Manager Escalations* — {label}"))

    if founder_open is not None:
        if int(founder_open) > 0:
            blocks.append(_section(f"🚨 *Founder-Level Escalations* — {founder_open} awaiting your review"))
        else:
            blocks.append(_section("✅ *Founder Escalations* — none"))

    if locked is not None:
        if int(locked) > 0:
            blocks.append(_section(f"⏸️ *Budget-Locked Clients* — {locked} client(s) with 0 hours"))
        else:
            blocks.append(_section("✅ *Budget Locks* — none"))

    # ── §2 Revenue Opportunities ─────────────────────────────────────────────
    blocks.append(_divider())
    blocks.append(_section("*§2 — Revenue Opportunities*"))
    rev = data.get("revenue", {})

    low = rev.get("low_balance_clients")
    if low is None:
        blocks.append(_section("⚠️ Low-balance data unavailable"))
    elif low:
        low_lines = [f"💡 *{len(low)} Client(s) Running Low on Hours (< {_LOW_HOURS_THRESHOLD}h)*"]
        for r in low[:8]:
            hrs = r.get("hours_balance", 0)
            low_lines.append(f"• {r.get('name', '?')} — {hrs:.1f}h remaining")
        blocks.append(_section("\n".join(low_lines)))
    else:
        blocks.append(_section(f"✅ *Low-Balance* — no active clients below {_LOW_HOURS_THRESHOLD}h"))

    new_24h = rev.get("new_customers_24h")
    if new_24h is not None and int(new_24h) > 0:
        blocks.append(_section(f"🆕 *{new_24h} new client(s) signed up in the last 24h*"))

    p7 = rev.get("purchases_7d")
    if p7 is not None:
        blocks.append(_section(f"💳 *Purchases last 7d* — {p7} processed Stripe event(s)"))

    total_hrs = rev.get("total_active_hours")
    if total_hrs is not None:
        blocks.append(_section(f"🏦 *Total active bucket hours across all clients* — {total_hrs:.1f}h"))

    # ── §3 Ops Bottlenecks ───────────────────────────────────────────────────
    blocks.append(_divider())
    blocks.append(_section("*§3 — Ops Bottlenecks*"))
    ops = data.get("ops", {})

    open_t = ops.get("open_todos")
    if open_t is not None:
        blocks.append(_section(f"📌 *Open Todos* — {open_t} in Basecamp"))

    open_m = ops.get("open_manager_interventions")
    if open_m is not None:
        emoji = "🔴" if int(open_m) > 5 else ("🟡" if int(open_m) > 0 else "✅")
        blocks.append(_section(f"{emoji} *Open Manager Interventions* — {open_m}"))

    acs = ops.get("acs_drafted")
    if acs is not None:
        blocks.append(_section(f"📝 *ACS Reports Awaiting VA Approval* — {acs}"))

    ck_healthy = ops.get("clockify_sync_healthy")
    last_sync = ops.get("last_clockify_sync")
    if ck_healthy is None:
        blocks.append(_section("⚠️ *Clockify Sync* — unable to check (table may not exist)"))
    elif ck_healthy:
        ts_str = last_sync.strftime("%H:%M UTC") if last_sync else "unknown"
        blocks.append(_section(f"✅ *Clockify Sync* — healthy (last sync {ts_str})"))
    else:
        ts_str = last_sync.strftime("%Y-%m-%d %H:%M UTC") if last_sync else "never"
        blocks.append(_section(f"🔴 *Clockify Sync* — STALE (last sync {ts_str})"))

    # ── §4 Website / Marketing ───────────────────────────────────────────────
    blocks.append(_divider())
    blocks.append(_section("*§4 — Website / Marketing*"))
    mkt = data.get("marketing", {})

    s7 = mkt.get("signups_7d")
    sp7 = mkt.get("signups_prior_7d")
    if s7 is not None and sp7 is not None:
        delta = int(s7) - int(sp7)
        sign = "+" if delta >= 0 else ""
        trend = "📈" if delta > 0 else ("📉" if delta < 0 else "➡️")
        blocks.append(_section(
            f"{trend} *New Signups* — {s7} this week vs {sp7} prior week ({sign}{delta})"
        ))
    elif s7 is not None:
        blocks.append(_section(f"📊 *New Signups this week* — {s7}"))

    wk = mkt.get("week_purchases", {})
    if wk:
        cnt = wk.get("cnt", 0)
        hrs = float(wk.get("total_hours", 0) or 0)
        blocks.append(_section(f"💳 *Purchases this calendar week* — {cnt} transactions, {hrs:.0f}h total"))

    blocks.append(_context("Note: GA/Vercel live traffic data not connected — signup data from DB only"))

    # ── §5 Recommended Actions ───────────────────────────────────────────────
    blocks.append(_divider())
    blocks.append(_section("*§5 — Recommended Actions*"))
    actions = data.get("recommended_actions", [])
    blocks.append(_section("\n".join(actions) if actions else "✅ Nothing urgent — smooth sailing"))

    # ── §6 Drafts Needing Approval ───────────────────────────────────────────
    blocks.append(_divider())
    blocks.append(_section("*§6 — Drafts Needing Approval*"))
    drafts = data.get("drafts", {})

    acs_d = drafts.get("acs_drafts")
    if acs_d is None:
        blocks.append(_section("⚠️ ACS draft data unavailable"))
    elif acs_d:
        d_lines = [f"📄 *{len(acs_d)} ACS Report(s) awaiting VA approval*"]
        for r in acs_d[:5]:
            title = r.get("title") or str(r.get("id", "untitled"))
            task_type = r.get("task_type") or "other"
            d_lines.append(f"• {title[:60]} ({task_type})")
        if len(acs_d) > 5:
            d_lines.append(f"  _…and {len(acs_d) - 5} more_")
        blocks.append(_section("\n".join(d_lines)))
    else:
        blocks.append(_section("✅ *ACS Reports* — none awaiting approval"))

    fnd = drafts.get("founder_interventions")
    if fnd is None:
        blocks.append(_section("⚠️ Founder intervention data unavailable"))
    elif fnd:
        fi_lines = [f"🚨 *{len(fnd)} Founder Intervention(s) Open*"]
        for iv in fnd:
            cname = iv.get("customer_name") or "unknown client"
            reason = (iv.get("reason") or "no reason given")[:80]
            fi_lines.append(f"• {cname} — {reason}")
        blocks.append(_section("\n".join(fi_lines)))
    else:
        blocks.append(_section("✅ *Founder Interventions* — none"))

    blocks.append(_divider())
    blocks.append(_context(
        f"Generated {now_utc.strftime('%Y-%m-%d %H:%M UTC')} · TB-Ops AI Wesley"
    ))

    # Compact fallback text
    risk_n = len(sla_br)
    low_n = len(rev.get("low_balance_clients") or [])
    action_n = len(actions)
    fallback = (
        f"Founder Brief {today_str}: "
        f"{risk_n} SLA breach(es), {low_n} low-balance client(s), "
        f"{action_n} recommended action(s). See brief for full details."
    )
    return blocks, fallback


# ─── Public API ───────────────────────────────────────────────────────────────

def build_founder_brief() -> dict:
    """Collect all signals and return a plain data dict.

    Safe to call without side effects — does not post to Slack.
    Never raises; each section catches its own errors.
    """
    db = SessionLocal()
    try:
        client_risks = _collect_client_risks(db)
        revenue = _collect_revenue_signals(db)
        ops = _collect_ops_bottlenecks(db)
        marketing = _collect_marketing_signals(db)
        drafts = _collect_drafts_pending(db)
    finally:
        db.close()

    data: dict[str, Any] = {
        "client_risks": client_risks,
        "revenue": revenue,
        "ops": ops,
        "marketing": marketing,
        "drafts": drafts,
    }
    data["recommended_actions"] = _build_recommended_actions(data)

    logger.info(
        "[founder_brief] signals: sla_breaches=%d at_risk=%d low_balance=%d "
        "founder_interventions=%s acs_drafted=%s open_todos=%s actions=%d",
        len(client_risks.get("sla_breaches", [])),
        len(client_risks.get("at_risk_clients", [])),
        len(revenue.get("low_balance_clients") or []),
        client_risks.get("founder_interventions_open"),
        ops.get("acs_drafted"),
        ops.get("open_todos"),
        len(data["recommended_actions"]),
    )
    return data


def send_founder_brief() -> dict:
    """Build the brief and post it to the founder's Slack channel/DM.

    Respects FOUNDER_BRIEF_ENABLED kill switch (set to '0' to pause).
    Returns {"ok": bool, ...}.
    """
    enabled = os.getenv("FOUNDER_BRIEF_ENABLED", "1").strip()
    if enabled == "0":
        logger.info("[founder_brief] FOUNDER_BRIEF_ENABLED=0 — skipping")
        return {"ok": False, "skipped": True, "reason": "FOUNDER_BRIEF_ENABLED=0"}

    channel = _founder_channel()
    if not channel:
        logger.warning(
            "[founder_brief] No channel configured — set FOUNDER_BRIEF_CHANNEL_ID "
            "or FOUNDER_DM_SLACK_USER_ID in env"
        )
        return {"ok": False, "error": "no_channel_configured"}

    try:
        data = build_founder_brief()
    except Exception as exc:
        logger.exception("[founder_brief] build failed")
        return {"ok": False, "error": str(exc)}

    today_str = datetime.now(timezone.utc).strftime("%b %-d, %Y")
    try:
        blocks, fallback = _fmt_founder_brief_blocks(data, today_str)
    except Exception as exc:
        logger.exception("[founder_brief] format failed")
        return {"ok": False, "error": f"format_failed: {exc}"}

    result = _post_message(channel, blocks, fallback)
    logger.info("[founder_brief] post ok=%s channel=%s", result.get("ok"), channel)
    return result
