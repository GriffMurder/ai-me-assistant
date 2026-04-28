-- Run this once in your Supabase SQL Editor to enable RAG long-term memory.

-- 1. Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Personal memory table
CREATE TABLE IF NOT EXISTS personal_memory (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. HNSW index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS personal_memory_embedding_idx
ON personal_memory USING hnsw (embedding vector_cosine_ops);

-- 4. Required match function used by langchain SupabaseVectorStore
CREATE OR REPLACE FUNCTION match_documents (
    query_embedding VECTOR(1536),
    match_count INT DEFAULT NULL,
    filter JSONB DEFAULT '{}'
) RETURNS TABLE (
    id BIGINT,
    content TEXT,
    metadata JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        personal_memory.id,
        personal_memory.content,
        personal_memory.metadata,
        1 - (personal_memory.embedding <=> query_embedding) AS similarity
    FROM personal_memory
    WHERE personal_memory.metadata @> filter
    ORDER BY personal_memory.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
