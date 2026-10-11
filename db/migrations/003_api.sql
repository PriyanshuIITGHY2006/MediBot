-- Phase 12: anonymous sessions, turn outcomes (no message text), feedback. Retention: 30 days (store.purge).
CREATE TABLE IF NOT EXISTS api_sessions (
    session_hash      text PRIMARY KEY,               -- sha256 of the session id; the raw id is never stored
    created_at        timestamptz NOT NULL DEFAULT now(),
    last_seen         timestamptz NOT NULL DEFAULT now(),
    acknowledged_at   timestamptz,
    disclaimer_sha256 text
);
CREATE TABLE IF NOT EXISTS api_turns (                 -- outcomes only: what kind of answer, how fast; never the text
    id              bigserial PRIMARY KEY,
    session_hash    text NOT NULL,
    turn_id         text NOT NULL UNIQUE,
    ts              timestamptz NOT NULL DEFAULT now(),
    intent          text,
    action          text,
    intercepted     boolean,
    emergency       boolean,
    medicine_found  boolean,
    substitutes     int,
    price_quotes    int,
    latency_ms      int,
    reader          text,
    narrator        text
);
CREATE INDEX IF NOT EXISTS api_turns_ts_idx ON api_turns (ts);
CREATE TABLE IF NOT EXISTS api_feedback (
    id            bigserial PRIMARY KEY,
    session_hash  text NOT NULL,
    turn_id       text,
    ts            timestamptz NOT NULL DEFAULT now(),
    rating        smallint NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment       text                               -- PII-scrubbed, max 500 chars
);
