-- Which model made each card's embedding (Phase 2 review, finding 4). Query vectors are
-- keyed by model; without this, a model change would compare new queries with old cards.
ALTER TABLE table_card ADD COLUMN embedding_model text;
UPDATE table_card SET embedding_model = 'voyage-4' WHERE embedding IS NOT NULL;
