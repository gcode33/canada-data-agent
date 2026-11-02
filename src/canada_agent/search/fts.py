"""Full-text table search over `table_card.tsv`.

The question's words are stemmed and stop-words dropped by Postgres, then ORed together.
`websearch_to_tsquery` would AND them, so a natural question ("How much does a litre of
regular gas cost in Toronto?") would need every word to match and return nothing.

`tsv` weights title words 'A' and member names 'D' with positions stripped (FTS_VERSION 2),
and ranking uses `ts_rank`. Measured on the retrieval set (evals/ablation.md): census-tract
tables list thousands of places, so with positions kept `ts_rank_cd` let "Toronto" x 900
outrank the right table (recall@5 0.13); counting each member word once lifted it to 0.33.
Neither is BM25 (no corpus-wide term weighting), which the README says.
"""

import psycopg

QUERY = """
WITH q AS (
    -- 'simple' + quoting: the lexemes are already stemmed; 'english' would stem them again
    -- (decreasing -> decreas -> decrea) and they would never match the stored vector.
    SELECT to_tsquery('simple', string_agg(DISTINCT quote_literal(lexeme), ' | ')) AS query
    FROM unnest(to_tsvector('english', %(question)s))
)
SELECT product_id
FROM table_card, q
WHERE q.query IS NOT NULL AND tsv @@ q.query
ORDER BY ts_rank(tsv, q.query) DESC, product_id
LIMIT %(limit)s
"""


def search_fts(conn: psycopg.Connection, question: str, limit: int = 50) -> list[int]:
    return [row[0] for row in conn.execute(QUERY, {"question": question, "limit": limit})]
