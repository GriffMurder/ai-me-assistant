-- Run this once in your Supabase SQL Editor to enable RAG long-term memory.
-- Safe to re-run; drops + recreates the table and function.

-- 1. Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- for gen_random_uuid()

-- 2. Personal memory table (UUID id to match langchain SupabaseVectorStore)
DROP TABLE IF EXISTS personal_memory CASCADE;
CREATE TABLE personal_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
    id UUID,
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
