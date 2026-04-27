from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
import sys
import os
import uuid

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))

from src.agent import get_me_agent
from src.workflows.weekly_plan import generate_weekly_plan

load_dotenv()

app = FastAPI(title="AI Me - Wesley's Personal Agent")

class ChatRequest(BaseModel):
    message: str
    thread_id: str = None  # For memory persistence

@app.post("/chat")
async def chat(request: ChatRequest):
    """Talk to your AI Me with memory"""
    thread_id = request.thread_id or str(uuid.uuid4())

    result = get_me_agent().invoke(
        {"messages": [{"role": "user", "content": request.message}]},
        config={"configurable": {"thread_id": thread_id}}
    )

    return {
        "response": result["messages"][-1].content,
        "thread_id": thread_id
    }

@app.post("/plan/weekly")
async def weekly_plan():
    """Generate Sunday night planning summary"""
    plan = generate_weekly_plan()
    return {"weekly_plan": plan}

@app.get("/")
async def root():
    return {"status": "✅ AI Me is running with memory", "message": "I now remember our conversations."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
