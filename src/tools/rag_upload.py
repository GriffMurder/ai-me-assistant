from datetime import datetime

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.memory.rag_memory import add_to_memory

_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)


def upload_note_from_text(text: str, title: str = "") -> int:
    """Split text into chunks and store each in long-term RAG memory.

    Args:
        text:  Raw text content to store.
        title: Human-readable label (e.g. filename) stored in metadata.

    Returns:
        Number of chunks stored.
    """
    chunks = _splitter.split_text(text.strip())
    ts = datetime.utcnow().isoformat()
    for i, chunk in enumerate(chunks):
        add_to_memory(chunk, metadata={
            "source": "upload",
            "title": title,
            "chunk": i,
            "total_chunks": len(chunks),
            "timestamp": ts,
        })
    return len(chunks)
