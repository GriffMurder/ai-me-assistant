from langgraph.checkpoint.postgres import PostgresSaver
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

_cm = None
_checkpointer = None
_setup_done = False

def get_checkpointer():
    global _cm, _checkpointer, _setup_done
    if _checkpointer is not None:
        return _checkpointer

    if not SUPABASE_DB_URL:
        print("⚠️ Using in-memory checkpointer (SUPABASE_DB_URL not set)")
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()
        return _checkpointer
    
    _cm = PostgresSaver.from_conn_string(SUPABASE_DB_URL)
    _checkpointer = _cm.__enter__()
    # Skip setup() - tables should already exist or will be created on first use
    print("✅ Using persistent Supabase checkpointer")
    return _checkpointer
