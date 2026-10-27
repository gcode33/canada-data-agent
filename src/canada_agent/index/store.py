"""Write table cards and members to Postgres, skipping tables whose content hasn't changed."""

from dataclasses import dataclass

import psycopg

from canada_agent.index.cards import fts_text, metadata_hash
from canada_agent.series.backend import TableMetadata


@dataclass(frozen=True)
class CardRow:
    meta: TableMetadata
    subject_codes: list[str]
    card_text: str
    fts: str
    hash: str

    @classmethod
    def from_metadata(
        cls, meta: TableMetadata, subject_codes: list[str], card_text: str, model: str
    ) -> "CardRow":
        fts = fts_text(meta)
        return cls(meta, subject_codes, card_text, fts, metadata_hash(card_text, fts, model))


def upsert_card(conn: psycopg.Connection, row: CardRow) -> bool:
    """Insert or update one table. Returns False (and writes nothing) if it is unchanged.

    A changed card clears `embedding`, so step 2.2 re-embeds exactly the changed tables.
    """
    m = row.meta
    with conn.transaction():
        current = conn.execute(
            "SELECT metadata_hash FROM table_card WHERE product_id = %s", (m.product_id,)
        ).fetchone()
        if current and current[0] == row.hash:
            return False
        conn.execute(
            """
            INSERT INTO table_card (product_id, title, subject_codes, frequency, start_date,
                                    end_date, card_text, tsv, embedding, metadata_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s,
                    setweight(to_tsvector('english', %s), 'A')
                    || setweight(strip(to_tsvector('english', %s)), 'D'),
                    NULL, %s)
            ON CONFLICT (product_id) DO UPDATE SET
                title = EXCLUDED.title, subject_codes = EXCLUDED.subject_codes,
                frequency = EXCLUDED.frequency, start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date, card_text = EXCLUDED.card_text,
                tsv = EXCLUDED.tsv, embedding = NULL, metadata_hash = EXCLUDED.metadata_hash,
                indexed_at = now()
            """,
            (
                m.product_id, m.title, row.subject_codes, m.frequency_code,
                m.start_date[:10] or None, m.end_date[:10] or None,
                row.card_text, m.title, row.fts, row.hash,
            ),
        )  # fmt: skip
        conn.execute("DELETE FROM member WHERE product_id = %s", (m.product_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO member (product_id, dimension_position, member_id, parent_id,"
                " name, terminated) VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (m.product_id, d.position, mem.id, mem.parent_id, mem.name, mem.terminated)
                    for d in m.dimensions
                    for mem in d.members
                ],
            )
    return True
