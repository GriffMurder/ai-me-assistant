from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

_pool = None
_checkpointer = None


def get_checkpointer():
    global _pool, _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    if not SUPABASE_DB_URL:
        print("⚠️ Using in-memory checkpointer (SUPABASE_DB_URL not set)")
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()
        return _checkpointer

    # prepare_threshold=0 disables psycopg3 prepared statements.
    # Required for Supabase PgBouncer (transaction mode) which cannot share
    # prepared statements across pooled connections.
    _pool = ConnectionPool(
        conninfo=SUPABASE_DB_URL,
        kwargs={"prepare_threshold": 0},
        min_size=1,
        max_size=5,
        open=True,
    )
    _checkpointer = PostgresSaver(_pool)
    try:
        _checkpointer.setup()
    except Exception as e:
        print(f"⚠️  Checkpointer setup skipped: {e}")
    print("✅ Using persistent Supabase checkpointer")
    return _checkpointer
