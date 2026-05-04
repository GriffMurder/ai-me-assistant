"""Tools for fetching live admin stats from Wesley's 4 business sites.

Each site exposes GET /api/admin/stats protected by an `x-admin-key` header.
The shared secret is stored in env var ADMIN_STATS_KEY.

Site URLs come from env vars: OPS_URL, TASKBULLET_URL, ORCARW_URL, RETURNFLOW_URL.
Tools fail gracefully — they return a string explaining the problem instead of raising.
"""
import os
import json
from typing import Optional

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

_TIMEOUT = 10.0


def _fetch_stats(site_label: str, url_env_var: str) -> str:
    """Internal: GET /api/admin/stats from the configured site, return formatted text."""
    base = os.getenv(url_env_var)
    key = os.getenv("ADMIN_STATS_KEY")

    if not base:
        return f"❌ {site_label}: env var {url_env_var} not set"
    if not key:
        return f"❌ {site_label}: env var ADMIN_STATS_KEY not set"

    url = base.rstrip("/") + "/api/admin/stats"
    try:
        r = httpx.get(url, headers={"x-admin-key": key}, timeout=_TIMEOUT)
    except Exception as e:
        return f"❌ {site_label}: request failed ({type(e).__name__}: {e})"

    if r.status_code == 401:
        return f"❌ {site_label}: unauthorized — ADMIN_STATS_KEY mismatch between this assistant and {site_label}"
    if r.status_code == 404:
        return f"❌ {site_label}: /api/admin/stats not found — endpoint not deployed yet"
    if r.status_code >= 500:
        return f"❌ {site_label}: server error {r.status_code} — {r.text[:200]}"
    if r.status_code != 200:
        return f"❌ {site_label}: HTTP {r.status_code} — {r.text[:200]}"

    try:
        data = r.json()
    except Exception:
        return f"❌ {site_label}: response was not JSON"

    # Pretty-format for the agent
    lines = [f"📊 {site_label} stats:"]
    for k, v in data.items():
        if k in ("site", "generated_at"):
            continue
        lines.append(f"  • {k}: {v}")
    if "generated_at" in data:
        lines.append(f"  (as of {data['generated_at']})")
    return "\n".join(lines)


@tool
def get_ops_dashboard() -> str:
    """Get live KPIs from the TaskBullet ops dashboard (ops.taskbullet.com).

    Returns health score, active VAs, total clients, open and overdue todos,
    open interventions, and hours logged today. This is the pulse of the company.
    """
    return _fetch_stats("ops.taskbullet.com", "OPS_URL")


@tool
def get_taskbullet_stats() -> str:
    """Get live signups and subscription stats from the public TaskBullet site (taskbullet.com)."""
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
