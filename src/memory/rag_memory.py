from datetime import datetime
import os

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from supabase import create_client

load_dotenv()

_client = None
_embeddings = None


def _get_client():
    """Lazy init Supabase client + embeddings."""
    global _client, _embeddings
    if _client is not None:
        return _client, _embeddings

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for RAG memory.")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set for embeddings.")

    _client = create_client(supabase_url, supabase_key)
    _embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return _client, _embeddings


def add_to_memory(content: str, metadata: dict = None):
    """Store important info about Wesley in long-term memory."""
    client, embeddings = _get_client()
    if metadata is None:
        metadata = {"source": "user_input", "timestamp": datetime.utcnow().isoformat()}
    vector = embeddings.embed_query(content)
    client.table("personal_memory").insert({
        "content": content,
        "metadata": metadata,
        "embedding": vector,
    }).execute()


def retrieve_relevant_memory(query: str, k: int = 6) -> str:
    """Retrieve most relevant past context for the current query."""
    client, embeddings = _get_client()
    vector = embeddings.embed_query(query)
    response = client.rpc("match_documents", {
        "query_embedding": vector,
        "match_count": k,
        "filter": {},
    }).execute()
    rows = response.data or []
    return "\n\n".join(row["content"] for row in rows)
