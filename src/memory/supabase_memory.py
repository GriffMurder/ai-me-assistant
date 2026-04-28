from langgraph.checkpoint.postgres import PostgresSaver
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

_cm = None
_checkpointer = None


def _conn_string() -> str:
    """Append prepare_threshold=0 so psycopg3 never uses prepared statements.
    Required when Supabase routes through PgBouncer in transaction mode."""
    url = SUPABASE_DB_URL
    sep = "&" if "?" in url else "?"
    if "prepare_threshold" not in url:
        url = f"{url}{sep}prepare_threshold=0"
    return url


def get_checkpointer():
    global _cm, _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    if not SUPABASE_DB_URL:
        print("⚠️ Using in-memory checkpointer (SUPABASE_DB_URL not set)")
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()
        return _checkpointer

    _cm = PostgresSaver.from_conn_string(_conn_string())
    _checkpointer = _cm.__enter__()
    print("✅ Using persistent Supabase checkpointer")
    return _checkpointer
