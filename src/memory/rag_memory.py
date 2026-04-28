from datetime import datetime
import os

from dotenv import load_dotenv
from langchain_community.vectorstores import SupabaseVectorStore
from langchain_openai import OpenAIEmbeddings
from supabase import create_client

load_dotenv()

_vector_store = None


def _get_vector_store():
    """Lazy init so missing env vars don't crash app startup."""
    global _vector_store
    if _vector_store is not None:
        return _vector_store

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set for RAG memory.")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set for embeddings.")

    client = create_client(supabase_url, supabase_key)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    _vector_store = SupabaseVectorStore(
        client=client,
        embedding=embeddings,
        table_name="personal_memory",
        query_name="match_documents",
    )
    return _vector_store


def add_to_memory(content: str, metadata: dict = None):
    """Store important info about Wesley in long-term memory."""
    if metadata is None:
        metadata = {"source": "user_input", "timestamp": datetime.utcnow().isoformat()}
    _get_vector_store().add_texts([content], metadatas=[metadata])


def retrieve_relevant_memory(query: str, k: int = 6) -> str:
    """Retrieve most relevant past context for the current query."""
    docs = _get_vector_store().similarity_search(query, k=k)
    return "\n\n".join(doc.page_content for doc in docs)
