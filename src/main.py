from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import base64
import re
import sys
import os
import uuid
import traceback

_TRANSCRIPT_PREFIX = re.compile(r'^(Human|User|Assistant|Thought|Action|Observation|Tool)\s*:\s*', re.IGNORECASE)

def _sanitize_response(text: str) -> str:
    """Strip any transcript-style prefix lines the model accidentally emits."""
    lines = text.splitlines()
    clean = [l for l in lines if not _TRANSCRIPT_PREFIX.match(l)]
    return "\n".join(clean).strip()

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.agent import get_me_agent
from src.workflows.email_automation import manual_email_triage
from src.auth.google_auth import build_flow, save_creds_from_flow, has_token
from src.tools.sms import send_sms
from src.utils.security import verify_owner, verify_twilio

load_dotenv()

# Allow Google to return broader scopes than requested (adds openid/userinfo automatically)
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def _materialize_google_token():
    """Backwards compat: decode legacy GOOGLE_TOKEN_B64 env var into token.json."""
    if os.path.exists("token.json"):
        return
    encoded = os.getenv("GOOGLE_TOKEN_B64")
    if not encoded:
        return
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
        with open("token.json", "w") as f:
            f.write(decoded)
        print("✅ token.json materialized from GOOGLE_TOKEN_B64")
    except Exception as e:
        print(f"⚠️  Failed to materialize token.json: {e}")


def _redirect_uri(request: Request) -> str:
    """Build the OAuth callback URL from the incoming request, honoring proxy headers."""
    base = os.getenv("OAUTH_REDIRECT_BASE")  # optional override
    if base:
        return base.rstrip("/") + "/auth/google/callback"
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host"))
    return f"{proto}://{host}/auth/google/callback"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _materialize_google_token()
    # --- Startup readiness check ---
    missing = []
    for key in ("XAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY",
                "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "MY_PHONE_NUMBER"):
        if not os.getenv(key):
            missing.append(key)
    if missing:
        print(f"⚠️  STARTUP: missing env vars: {', '.join(missing)}")
    else:
        print("✅ STARTUP: all required env vars present")
    if not has_token():
        print("⚠️  STARTUP: Google token missing — visit /auth/google to authorize")
    else:
        print("✅ STARTUP: Google token present")
    # --- Scheduler ---
    try:
        from src.workflows.automation import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"⚠️  Scheduler disabled during startup: {e}")
    yield


app = FastAPI(title="AI Me - Wesley's Personal Agent", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = None  # For memory persistence

@app.post("/chat", dependencies=[Depends(verify_owner)])
async def chat(request: ChatRequest):
    """Talk to your AI Me with memory"""
    thread_id = request.thread_id or str(uuid.uuid4())
    try:
        result = get_me_agent().invoke(
            {"messages": [{"role": "user", "content": request.message}]},
            config={"configurable": {"thread_id": thread_id}}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})

    return {
        "response": _sanitize_response(result["messages"][-1].content),
        "thread_id": thread_id
    }

@app.post("/email/triage", dependencies=[Depends(verify_owner)])
async def trigger_email_triage():
    """Manually trigger proactive inbox triage. Creates drafts for reply-needed emails."""
    report = await manual_email_triage()
    return {"status": "Email triage complete", "report": report}


@app.post("/sms", dependencies=[Depends(verify_twilio)])
async def sms_webhook(request: Request):
    """Twilio SMS webhook — receives an incoming text, runs the agent, replies via SMS."""
    # Note: verify_twilio already consumed and validated the form body.
    # Re-read it here (FastAPI caches the form parse within the request lifetime).
    form = await request.form()
    incoming_message = form.get("Body", "")
    from_number = form.get("From", "")

    if not incoming_message or not from_number:
        return {"status": "ignored"}

    result = get_me_agent().invoke(
        {"messages": [{"role": "user", "content": incoming_message}]},
        config={"configurable": {"thread_id": f"sms-{from_number}"}},
    )
    reply = result["messages"][-1].content

    # Truncate to SMS limit (1600 chars to leave room for Twilio overhead)
    send_sms(from_number, reply[:1600])

    return {"status": "ok"}


@app.post("/voice", dependencies=[Depends(verify_twilio)])
async def voice_webhook(request: Request):
    """Twilio Voice webhook — spoken conversation with Me."""
    from twilio.twiml.voice_response import VoiceResponse, Gather
    form = await request.form()
    call_sid = form.get("CallSid", "unknown")
    speech = form.get("SpeechResult", "").strip()

    if speech:
        try:
            result = get_me_agent().invoke(
                {"messages": [{"role": "user", "content": speech}]},
                config={"configurable": {"thread_id": f"voice-{call_sid}"}},
            )
            reply = _sanitize_response(result["messages"][-1].content)[:500]
        except Exception as e:
            reply = "Sorry, I ran into an issue. Try again."
            print(f"Voice agent error: {e}")
    else:
        reply = "Hey, it's Me. What do you need?"

    resp = VoiceResponse()
    gather = Gather(input="speech", action="/voice", timeout=5, speechTimeout="auto")
    gather.say(reply, voice="Polly.Joanna")
    resp.append(gather)
    # Fallback if caller says nothing after timeout
    resp.say("I didn't catch that. Call back anytime.", voice="Polly.Joanna")
    return Response(content=str(resp), media_type="text/xml")


@app.get("/drafts", dependencies=[Depends(verify_owner)])
async def get_drafts():
    """List current Gmail drafts as structured JSON."""
    try:
        from src.tools.email import _list_gmail_drafts
        drafts = _list_gmail_drafts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch drafts: {e}")
    return {"drafts": drafts}


@app.post("/drafts/{draft_id}/send", dependencies=[Depends(verify_owner)])
async def send_draft(draft_id: str):
    """Send a Gmail draft by id."""
    try:
        from src.tools.email import _send_gmail_draft
        _send_gmail_draft(draft_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not send draft: {e}")
    return {"sent": True, "draft_id": draft_id}


@app.get("/plan/weekly", dependencies=[Depends(verify_owner)])
async def weekly_plan():
    """Manually trigger weekly plan"""
    try:
        from src.workflows.automation import send_weekly_plan
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Weekly planner unavailable: {e}")
    plan = await send_weekly_plan()
    return {"status": "Weekly plan generated", "plan": plan}

@app.post("/upload", dependencies=[Depends(verify_owner)])
async def upload_note(file: UploadFile = File(...)):
    """Upload a .txt or .md file into long-term RAG memory."""
    allowed = {".txt", ".md"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Only .txt and .md are accepted.",
        )
    try:
        from src.tools.rag_upload import upload_note_from_text
        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")
        chunks = upload_note_from_text(text, title=file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    return {"chunks": chunks, "title": file.filename}


@app.get("/")
async def root():
    """Serve the chat UI"""
    return FileResponse("static/index.html")

@app.get("/api")
async def api_status():
    return {"status": "✅ AI Me is running with automation", "message": "Daily briefing (7am) & weekly plan (Sun 8pm) active"}

@app.get("/health")
async def health():
    """Public health check — minimal to avoid leaking config info."""
    return {"status": "ok"}


@app.get("/health/full", dependencies=[Depends(verify_owner)])
async def health_full():
    """Full diagnostics — owner only."""
    keys = ["XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_URL",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER",
            "MY_PHONE_NUMBER", "APP_PASSWORD"]
    status = {k: ("set" if os.getenv(k) else "MISSING") for k in keys}
    status["google_token"] = "present" if has_token() else "MISSING (visit /auth/google to authorize)"
    try:
        import twilio  # noqa: F401
        status["twilio_module"] = "installed"
    except ImportError:
        status["twilio_module"] = "MISSING"
    return status


OAUTH_STATE_COOKIE = "google_oauth_state"
OAUTH_VERIFIER_COOKIE = "google_oauth_verifier"


@app.get("/diagnostics", dependencies=[Depends(verify_owner)])
async def diagnostics():
    """Owner-only: real-time subsystem health — Google, Twilio, Supabase, scheduler, reminders."""
    from datetime import timezone as _tz
    result: dict = {}

    # --- Google ---
    try:
        from src.auth.google_auth import load_creds
        creds = load_creds()
        result["google"] = {
            "token_present": True,
            "valid": creds.valid,
            "expired": creds.expired,
            "has_refresh_token": bool(creds.refresh_token),
            "scopes": list(creds.scopes or []),
        }
    except Exception as e:
        result["google"] = {"token_present": False, "error": str(e)}

    # --- Twilio ---
    from src.tools.sms import _twilio_configured
    twilio_ok, twilio_reason = _twilio_configured()
    result["twilio"] = {
        "configured": twilio_ok,
        "my_phone_set": bool(os.getenv("MY_PHONE_NUMBER")),
        "reason": twilio_reason or "ok",
    }

    # --- Supabase ---
    try:
        from supabase import create_client as _sb
        sb = _sb(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        sb.table("reminders").select("id").limit(1).execute()
        result["supabase"] = {"connected": True}
    except Exception as e:
        result["supabase"] = {"connected": False, "error": str(e)}

    # --- Scheduler ---
    try:
        from src.workflows.automation import scheduler as _sched
        jobs = []
        for job in _sched.get_jobs():
            next_run = job.next_run_time
            jobs.append({
                "id": job.id,
                "next_run": next_run.isoformat() if next_run else "paused",
            })
        result["scheduler"] = {"running": _sched.running, "jobs": jobs}
    except Exception as e:
        result["scheduler"] = {"running": False, "error": str(e)}

    # --- Reminders ---
    try:
        from supabase import create_client as _sb2
        from datetime import datetime as _dt
        sb2 = _sb2(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
        now_iso = _dt.now(_tz.utc).isoformat()
        pending = sb2.table("reminders").select("id", count="exact").eq("fired", False).execute()
        overdue = sb2.table("reminders").select("id", count="exact").eq("fired", False).lte("remind_at", now_iso).execute()
        result["reminders"] = {
            "pending": pending.count,
            "overdue": overdue.count,
        }
    except Exception as e:
        result["reminders"] = {"error": str(e)}

    return result


@app.post("/diagnostics/check-reminders", dependencies=[Depends(verify_owner)])
async def manual_check_reminders():
    """Owner-only: force-run the reminder check job right now. Use to test without waiting an hour."""
    try:
        from src.workflows.automation import check_reminders
        await check_reminders()
        return {"status": "ok", "message": "Reminder check complete — see Render logs for details"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reminder check failed: {e}")



async def auth_google_start(request: Request):
    """Kick off Google OAuth. Visit this in a browser, click Allow, done."""
    flow = build_flow(_redirect_uri(request))
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh_token issuance
    )
    response = RedirectResponse(auth_url)
    # Persist OAuth state + PKCE verifier in cookies so callback works across instances.
    response.set_cookie(OAUTH_STATE_COOKIE, state, max_age=600, httponly=True, secure=True, samesite="lax")
    response.set_cookie(OAUTH_VERIFIER_COOKIE, flow.code_verifier or "", max_age=600, httponly=True, secure=True, samesite="lax")
    return response


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    """Google redirects here after user clicks Allow. Saves token to Supabase."""
    try:
        returned_state = request.query_params.get("state")
        expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
        code_verifier = request.cookies.get(OAUTH_VERIFIER_COOKIE)

        if not returned_state or not expected_state or returned_state != expected_state:
            raise RuntimeError("OAuth state mismatch. Start again at /auth/google")
        if not code_verifier:
            raise RuntimeError("Missing OAuth code verifier. Start again at /auth/google")

        flow = build_flow(_redirect_uri(request))
        flow.fetch_token(
            authorization_response=str(request.url),
            code_verifier=code_verifier,
        )
        save_creds_from_flow(flow)
    except Exception as e:
        response = HTMLResponse(
            f"<h2>OAuth failed</h2><pre>{traceback.format_exc()}</pre>",
            status_code=500,
        )
        response.delete_cookie(OAUTH_STATE_COOKIE)
        response.delete_cookie(OAUTH_VERIFIER_COOKIE)
        return response
    response = HTMLResponse(
        "<h2>✅ Google authorized.</h2>"
        "<p>Token saved to Supabase. Calendar + Gmail tools are live.</p>"
        "<p><a href='/'>Back to chat</a></p>"
    )
    response.delete_cookie(OAUTH_STATE_COOKIE)
    response.delete_cookie(OAUTH_VERIFIER_COOKIE)
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
