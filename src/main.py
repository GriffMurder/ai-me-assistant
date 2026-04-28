from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import base64
import sys
import os
import uuid
import traceback

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.agent import get_me_agent
from src.workflows.automation import start_scheduler, weekly_planning
from src.auth.google_auth import build_flow, save_creds_from_flow, has_token

load_dotenv()


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
    start_scheduler()
    yield


app = FastAPI(title="AI Me - Wesley's Personal Agent", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str
    thread_id: str = None  # For memory persistence

@app.post("/chat")
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
        "response": result["messages"][-1].content,
        "thread_id": thread_id
    }

@app.get("/plan/weekly")
async def weekly_plan():
    """Manually trigger weekly plan"""
    plan = await weekly_planning()
    return {"status": "Weekly plan generated", "plan": plan}

@app.get("/")
async def root():
    """Serve the chat UI"""
    return FileResponse("static/index.html")

@app.get("/api")
async def api_status():
    return {"status": "✅ AI Me is running with automation", "message": "Daily briefing (7am) & weekly plan (Sun 8pm) active"}

@app.get("/health")
async def health():
    """Check env vars and dependencies without invoking the agent"""
    keys = ["XAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_DB_URL",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
    status = {k: ("set" if os.getenv(k) else "MISSING") for k in keys}
    status["google_token"] = "present" if has_token() else "MISSING (visit /auth/google to authorize)"
    return status


# Store pending OAuth flows by state so the callback can reuse the same object
# (needed to carry the PKCE code_verifier across the redirect).
_pending_flows: dict = {}


@app.get("/auth/google")
async def auth_google_start(request: Request):
    """Kick off Google OAuth. Visit this in a browser, click Allow, done."""
    flow = build_flow(_redirect_uri(request))
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh_token issuance
    )
    _pending_flows[state] = flow
    return RedirectResponse(auth_url)


@app.get("/auth/google/callback")
async def auth_google_callback(request: Request):
    """Google redirects here after user clicks Allow. Saves token to Supabase."""
    try:
        state = request.query_params.get("state")
        flow = _pending_flows.pop(state, None)
        if flow is None:
            # Fallback: build fresh flow (works if PKCE wasn't used)
            flow = build_flow(_redirect_uri(request))
        flow.fetch_token(authorization_response=str(request.url))
        save_creds_from_flow(flow)
    except Exception as e:
        return HTMLResponse(
            f"<h2>OAuth failed</h2><pre>{traceback.format_exc()}</pre>",
            status_code=500,
        )
    return HTMLResponse(
        "<h2>✅ Google authorized.</h2>"
        "<p>Token saved to Supabase. Calendar + Gmail tools are live.</p>"
        "<p><a href='/'>Back to chat</a></p>"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
