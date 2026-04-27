from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import sys
import os
import uuid
import traceback

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.agent import get_me_agent
from src.workflows.automation import start_scheduler, weekly_planning

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.post("/plan/weekly")
async def weekly_plan():
    """Manually trigger weekly plan"""
    plan = await weekly_planning()
    return {"status": "Weekly plan generated", "plan": plan}

@app.get("/")
async def root():
    return {"status": "✅ AI Me is running with automation", "message": "Daily briefing (7am) & weekly plan (Sun 8pm) active"}

@app.get("/health")
async def health():
    """Check env vars and dependencies without invoking the agent"""
    xai_key = os.getenv("XAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    supabase_url = os.getenv("SUPABASE_URL")
    db_url = os.getenv("SUPABASE_DB_URL")
    return {
        "XAI_API_KEY": "set" if xai_key else "MISSING",
        "ANTHROPIC_API_KEY": "set" if anthropic_key else "MISSING",
        "SUPABASE_URL": "set" if supabase_url else "MISSING",
        "SUPABASE_DB_URL": "set" if db_url else "not set (using in-memory)",
        "token.json": "present" if os.path.exists("token.json") else "MISSING (Google tools disabled)",
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
