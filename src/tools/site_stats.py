"""Tools for fetching live admin stats and financials from Wesley's business sites.

Each site exposes GET /api/admin/stats protected by an Authorization: Bearer header.
Financial endpoints use GET /api/admin/financials with a dedicated bearer key.

Site URLs come from env vars: OPS_URL, TASKBULLET_URL, ORCARW_URL, RETURNFLOW_URL, STRAWS_URL.
Tools fail gracefully — they return a string explaining the problem instead of raising.
"""
import os

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

_TIMEOUT = 10.0


def _fmt_list_preview(items: list) -> str:
    """Compact preview for lists of strings or small dict objects."""
    preview = []
    for item in items[:5]:
        if isinstance(item, dict):
            if "name" in item and "ytd" in item:
                preview.append(f"{item['name']}: {item['ytd']}")
            elif "section" in item and "reason" in item:
                preview.append(f"{item['section']}: {item['reason']}")
            elif "name" in item:
                preview.append(str(item["name"]))
            else:
                preview.append(str(item))
        else:
            preview.append(str(item))
    return ", ".join(preview)


def _fmt_nested(data: dict) -> str:
    """Format a potentially-nested stats response into readable lines.

    Tolerant of both snake_case and camelCase field names (TaskBullet uses camelCase).
    Handles traffic.last7/last30 as metric objects and activePlans as an array.
    """
    lines = []
    skip = {"site", "source", "generated_at", "generatedAt"}

    for section, value in data.items():
        if section in skip:
            continue
        if isinstance(value, dict):
            lines.append(f"  [{section}]")
            for k, v in value.items():
                # traffic.last7 / traffic.last30 may be metric objects {sessions, users, ...}
                if isinstance(v, dict):
                    sessions = v.get("sessions", v.get("pageviews", "?"))
                    lines.append(f"    • {k}: {sessions} sessions")
                elif isinstance(v, list):
                    if k == "activePlans":
                        names = [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in v]
                        lines.append(f"    • activePlans ({len(v)}): {', '.join(names)}")
                    else:
                        lines.append(f"    • {k} ({len(v)}): {_fmt_list_preview(v)}")
                else:
                    lines.append(f"    • {k}: {v}")
        elif isinstance(value, list):
            lines.append(f"  • {section} ({len(value)}): {_fmt_list_preview(value)}")
        else:
            lines.append(f"  • {section}: {value}")

    # Accept both snake_case and camelCase timestamp
    ts = data.get("generatedAt") or data.get("generated_at")
    if ts:
        lines.append(f"  (as of {ts})")
    return "\n".join(lines)


def _fetch_admin_json(site_label: str, url_env_var: str, path: str, key_env_var: str) -> tuple[dict | None, str | None]:
    """Internal: fetch a JSON admin endpoint with bearer auth."""
    base = os.getenv(url_env_var)
    key = os.getenv(key_env_var)

    if not base:
        return None, f"❌ {site_label}: env var {url_env_var} not set"
    if not key:
        return None, f"❌ {site_label}: env var {key_env_var} not set"

    url = base.rstrip("/") + path
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
    except Exception as e:
        return None, f"❌ {site_label}: request failed ({type(e).__name__}: {e})"

    if r.status_code in (401, 403):
        return None, f"❌ {site_label}: auth failed (HTTP {r.status_code}) — {key_env_var} in Render doesn't match the token {site_label} expects."
    if r.status_code == 404:
        return None, f"❌ {site_label}: {path} not found — endpoint not deployed yet"
    if r.status_code >= 500:
        return None, f"❌ {site_label}: endpoint failed (HTTP {r.status_code}) — {r.text[:200]}"
    if r.status_code != 200:
        return None, f"❌ {site_label}: HTTP {r.status_code} — {r.text[:200]}"

    try:
        data = r.json()
    except Exception:
        return None, f"❌ {site_label}: response was not JSON"

    return data, None


def _fetch_stats(site_label: str, url_env_var: str) -> str:
    """Internal: GET /api/admin/stats from the configured site, return formatted text."""
    data, error = _fetch_admin_json(site_label, url_env_var, "/api/admin/stats", "ADMIN_STATS_KEY")
    if error:
        return error

    return f"📊 {site_label} stats:\n{_fmt_nested(data)}"


def _fetch_financials(site_label: str, url_env_var: str) -> str:
    """Internal: GET /api/admin/financials from the configured site, return formatted text."""
    data, error = _fetch_admin_json(site_label, url_env_var, "/api/admin/financials", "ADMIN_FINANCIALS_KEY")
    if error:
        return error

    return f"💰 {site_label} financials:\n{_fmt_nested(data)}"


@tool
def get_ops_dashboard() -> str:
    """Get live KPIs from the TaskBullet ops dashboard (ops.taskbullet.com).

    Returns health score, active VAs, total clients, open and overdue todos,
    open interventions, and hours logged today. This is the pulse of the company.
    """
    return _fetch_stats("ops.taskbullet.com", "OPS_URL")


@tool
def get_taskbullet_stats() -> str:
    """Get live billing, business, and traffic stats from TaskBullet (taskbullet.com).

    Response uses camelCase. Key fields:
    - billing: activeSubscriptions, trialingSubscriptions, pastDueSubscriptions, estimatedMrrUsd
    - business: activeClients, payingClients, newPaidClients30d, leads30d, kickoffBookings30d,
                leadToKickoffRate30d, activePlans (array of plan objects), avgHoursSaved
    - traffic: last7 (metric object with .sessions), last30 (metric object with .sessions), dataSource

    Flag past-due subscriptions, weak lead-to-kickoff rate, or missing GA4 traffic data.
    """
    return _fetch_stats("taskbullet.com", "TASKBULLET_URL")


@tool
def get_orcarw_stats() -> str:
    """Get live user, signup, and engagement stats from the OrcaRW VA marketplace (orcarw.com)."""
    return _fetch_stats("orcarw.com", "ORCARW_URL")


@tool
def get_returnflow_stats() -> str:
    """Get live tenant and SMS message stats from the ReturnFlow SMS app (returnflowhq.com)."""
    return _fetch_stats("returnflowhq.com", "RETURNFLOW_URL")


@tool
def get_taskbullet_financials() -> str:
    """Get live TaskBullet financials: revenue, MRR, subscriptions, payouts, and expenses when available."""
    return _fetch_financials("taskbullet.com", "TASKBULLET_URL")


@tool
def get_straws_financials() -> str:
    """Get live Straws financials from the site's /api/admin/financials endpoint.

    Straws returns USD amounts as numeric dollars, not cents or strings.
    recurring is currently not applicable, and expenses may be unavailable.
    Always read availability and errors before treating null values as real numbers.
    """
    return _fetch_financials("strawssoda.com", "STRAWS_URL")


@tool
def get_all_site_stats() -> str:
    """Get a combined snapshot of all 4 businesses at once: ops, TaskBullet, OrcaRW, ReturnFlow.

    Use this for any 'how are my businesses doing' or morning briefing question.
    """
    sections = [
        get_ops_dashboard.invoke({}),
        get_taskbullet_stats.invoke({}),
        get_orcarw_stats.invoke({}),
        get_returnflow_stats.invoke({}),
    ]
    return "\n\n".join(sections)


@tool
def get_all_financials() -> str:
    """Get a combined TaskBullet + Straws financial snapshot.

    Use this for direct revenue, subscription, payout, or expense questions.
    """
    sections = [
        get_taskbullet_financials.invoke({}),
        get_straws_financials.invoke({}),
    ]
    return "\n\n".join(sections)
