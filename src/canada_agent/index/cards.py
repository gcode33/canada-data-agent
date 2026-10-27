"""Table cards: the compact text that represents one table in search (SPEC §7.2).

A full table can be ~55k tokens (CPI: 359 products x 30 places), far too big to embed.
A card keeps what helps a search match - title, frequency, date range, dimension names
with counts, a few members per dimension - in about 600 tokens. Every member name still
goes into the full-text index (`fts_text`), so a deep member like CPI's "Rent" (depth 3,
not on the card) is still findable by keyword.
"""

import hashlib

from canada_agent.series.backend import Dimension, TableMetadata
from canada_agent.untrusted import untrusted_text

CARD_CHAR_LIMIT = 2400  # ~600 tokens at ~4 characters per token
MEMBERS_PER_DIMENSION = 25
FOOTNOTE_LIMIT = 300
FTS_CHAR_LIMIT = 400_000  # Postgres tsvector values must stay under 1 MB

# From WDS getCodeSets "frequency" (checked 2026-10-27). Note 21 is "Occasional Daily":
# some tables you'd call quarterly are coded that way.
FREQUENCIES = {
    1: "daily", 2: "weekly", 4: "biweekly", 6: "monthly", 7: "bimonthly", 9: "quarterly",
    11: "semi-annual", 12: "annual", 13: "every 2 years", 14: "every 3 years",
    15: "every 4 years", 16: "every 5 years", 17: "every 10 years", 18: "occasional",
    19: "occasional quarterly", 20: "occasional monthly", 21: "occasional daily",
}  # fmt: skip


def table_number(product_id: int) -> str:
    """18100004 -> "18-10-0004", the form StatCan prints on its pages."""
    s = str(product_id)
    return f"{s[:2]}-{s[2:4]}-{s[4:]}"


def _depths(dim: Dimension) -> dict[int, int]:
    parents = {m.id: m.parent_id for m in dim.members}

    def depth(member_id: int, hops: int = 0) -> int:
        parent = parents.get(member_id)
        if parent is None or parent not in parents or hops > 50:
            return hops
        return depth(parent, hops + 1)

    return {m.id: depth(m.id) for m in dim.members}


def _dimension_line(dim: Dimension) -> str:
    depth = _depths(dim)
    ordered = sorted(dim.members, key=lambda m: (depth[m.id], m.name.casefold()))
    names = [untrusted_text(m.name, 80) for m in ordered[:MEMBERS_PER_DIMENSION]]
    more = ", …" if len(ordered) > MEMBERS_PER_DIMENSION else ""
    return f"- {untrusted_text(dim.name, 80)} ({len(dim.members)}): {', '.join(names)}{more}"


def build_card(meta: TableMetadata, subject_names: list[str]) -> str:
    header = [
        f"[{table_number(meta.product_id)}] {untrusted_text(meta.title, 300)}",
        " · ".join(
            part
            for part in (
                f"Frequency: {FREQUENCIES.get(meta.frequency_code, 'unknown')}",
                f"Range: {meta.start_date[:7]} to {meta.end_date[:7]}" if meta.start_date else "",
                f"Subject: {', '.join(subject_names)}" if subject_names else "",
            )
            if part
        ),
        "Dimensions:",
    ]
    note = untrusted_text(meta.footnotes[0], FOOTNOTE_LIMIT) if meta.footnotes else ""
    footer = [f"Note: {note}"] if note else []

    lines = header + [_dimension_line(d) for d in meta.dimensions] + footer
    card = "\n".join(lines)
    while len(card) > CARD_CHAR_LIMIT and len(lines) > len(header) + len(footer):
        # Drop the last dimension line until it fits; the counts on earlier lines remain.
        lines.pop(len(lines) - len(footer) - 1)
        card = "\n".join(lines + ["- … more dimensions"])
    return card[:CARD_CHAR_LIMIT]


def fts_text(meta: TableMetadata) -> str:
    """Title, dimension names and EVERY member name, for the full-text index."""
    seen: dict[str, None] = {meta.title: None}
    for dim in meta.dimensions:
        seen[dim.name] = None
        for member in dim.members:
            seen[member.name] = None
    return " | ".join(seen)[:FTS_CHAR_LIMIT]


# Bump when the way `tsv` is built changes, so existing rows are rebuilt.
# v2: title weighted 'A' with positions; member names 'D' with positions stripped, so a word
# counts once per table however many members repeat it (see evals/ablation.md).
FTS_VERSION = "2"


def metadata_hash(card_text: str, fts: str, model: str) -> str:
    """Changes whenever the card, the full-text source or build, or the model changes."""
    parts = (card_text, fts, model, FTS_VERSION)
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
