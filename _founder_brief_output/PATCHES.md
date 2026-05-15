# Founder Brief — Implementation Patches

## File 1: `app/founder_brief.py`
**Action:** Create new file — full content is at `app/founder_brief.py` in this directory.

---

## File 2: `app/workers.py` — two edits

### Edit A: Add entry to `beat_schedule` dict

Find this near the end of the `beat_schedule` dict (the last crontab entry):

```python
        "schedule": crontab(minute=5),  # :05 past every hour
    },
}
```

Replace with:

```python
        "schedule": crontab(minute=5),  # :05 past every hour
    },
    "founder-brief-daily": {
        "task": "app.workers.send_founder_brief",
        "schedule": crontab(minute=5, hour=8, day_of_week="1-5"),
    },
}
```

### Edit B: Add Celery task function

Find the `send_daily_ops_digest` task function. It looks like:

```python
@celery_app.task(name="app.workers.send_daily_ops_digest")
def send_daily_ops_digest():
    ...
    return result
```

Add this new task **immediately after** that function (after the last `return result` line):

```python

@celery_app.task(name="app.workers.send_founder_brief")
def send_founder_brief():
    """Daily Founder Brief — 8:05 AM Mon–Fri CT → FOUNDER_BRIEF_CHANNEL_ID."""
    from .founder_brief import send_founder_brief as _send
    logger.info("[workers] Sending Founder Brief...")
    result = _send()
    logger.info("[workers] Founder Brief finished: %s", result)
    return result
```

---

## File 3: `app/main.py` — one edit

Find the existing `/ops/digest/send` debug route. It will look like:

```python
@app.post("/ops/digest/send")
def ops_digest_send(mode: str = "daily"):
    ...
    return result
```

Add this new route **immediately after** that function:

```python

@app.post("/debug/founder-brief/run-once")
def debug_founder_brief_run_once(dry_run: bool = True):
    """Run the Founder Brief once for debugging.

    dry_run=true (default) returns blocks + data JSON without posting to Slack.
    dry_run=false actually posts to the configured channel.
    """
    from .founder_brief import build_founder_brief, _fmt_founder_brief_blocks
    from datetime import datetime, timezone

    data = build_founder_brief()
    today_str = datetime.now(timezone.utc).strftime("%b %-d, %Y")
    blocks, fallback = _fmt_founder_brief_blocks(data, today_str)

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "data": data,
            "blocks": blocks,
            "fallback": fallback,
        }

    from .founder_brief import send_founder_brief
    return send_founder_brief()
```

---

## Optional: Add env var to `app/config.py`

In the `Settings` class, after the `FOUNDER_DM_SLACK_USER_ID` entry, optionally add:

```python
    # Optional override channel for the daily Founder Brief.
    # Falls back to FOUNDER_DM_SLACK_USER_ID if not set.
    FOUNDER_BRIEF_CHANNEL_ID: str | None = os.getenv("FOUNDER_BRIEF_CHANNEL_ID")
    # Set to "0" to disable the daily Founder Brief without removing the beat schedule.
    FOUNDER_BRIEF_ENABLED: str = os.getenv("FOUNDER_BRIEF_ENABLED", "1")
```

(Not strictly required — `founder_brief.py` reads env vars directly.)

---

## Verification

After deploying:

1. **Dry run (no Slack post):**
   ```
   POST /debug/founder-brief/run-once?dry_run=true
   ```
   Check that all 6 sections are present in the `data` dict and `blocks` array.

2. **Live run (posts to Slack):**
   ```
   POST /debug/founder-brief/run-once?dry_run=false
   ```
   Confirm the brief appears in `FOUNDER_BRIEF_CHANNEL_ID` or the founder's DM.

3. **Structured log line to watch for:**
   ```
   [founder_brief] signals: sla_breaches=N at_risk=N low_balance=N ...
   ```

4. **Kill switch** (if needed):
   Set env var `FOUNDER_BRIEF_ENABLED=0` to pause delivery without removing the beat entry.
