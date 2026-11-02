-- Rerank results, recorded once and replayed like query embeddings, so evals and CI run
-- the reranked pipeline with no Voyage key. Keyed by the exact candidate list: if search
-- changes the candidates, the old ordering no longer applies and is simply not found.
CREATE TABLE rerank_cache (
    model           text        NOT NULL,
    question_hash   text        NOT NULL,
    candidates_hash text        NOT NULL,   -- sha256 of the ordered candidate product ids
    ranked          bigint[]    NOT NULL,   -- product ids, most relevant first
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model, question_hash, candidates_hash)
);
