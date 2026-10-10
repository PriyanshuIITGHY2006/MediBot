-- Phase 10: grounded health answers. Evidence passages with their citation, lexical + vector search.
ALTER TABLE evidence_chunks ADD COLUMN IF NOT EXISTS title text;                    -- citation label
ALTER TABLE evidence_chunks ADD COLUMN IF NOT EXISTS url   text;                    -- citation link
ALTER TABLE evidence_chunks ADD COLUMN IF NOT EXISTS meta  jsonb;                   -- written_for, label type, dates
ALTER TABLE evidence_chunks ADD COLUMN IF NOT EXISTS tsv   tsvector
    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;
CREATE INDEX IF NOT EXISTS evidence_chunks_tsv_idx ON evidence_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS evidence_chunks_vec_idx ON evidence_chunks USING hnsw (embedding vector_cosine_ops);
