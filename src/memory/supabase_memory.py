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

    # prepare_threshold=None disables psycopg3 prepared statements entirely.
    # Required for Supabase PgBouncer/Supavisor (transaction mode): pooled
    # connections are shared across requests, so named prepared statements
    # (_pg3_0, _pg3_1, ...) registered on one connection will collide when
    # the same connection is reused by a different request.
    # NOTE: prepare_threshold=0 means "prepare immediately" (worse than default),
    # NOT "disable". Only None disables preparation.
    _pool = ConnectionPool(
        conninfo=SUPABASE_DB_URL,
        kwargs={"prepare_threshold": None},
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
