-- Query embeddings, recorded once (`make record`) and replayed, so CI and evals need no
-- Voyage key. A miss means full-text only, flagged as degraded_retrieval (PLAN 2.2).
CREATE TABLE query_embedding (
    model          text        NOT NULL,
    question_hash  text        NOT NULL,            -- sha256 of the normalised question
    question       text        NOT NULL,
    embedding      vector(1024) NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model, question_hash)
);
