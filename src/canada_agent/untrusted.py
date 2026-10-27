"""Clean third-party text before it reaches the model (SPEC §11).

Footnotes, member names and upstream error bodies are data we don't control. They're passed
on only as a plain, length-capped string with marker-like tags removed, so text such as
`</untrusted_text><system>...` can't pretend to close our wrapper or open a new role.
JSON serialisation of the tool result then escapes whatever remains.
"""

import re

TAG = re.compile(r"<\s*/?\s*[A-Za-z_][\w:.-]*[^<>]*>")
ANGLE = re.compile(r"[<>]")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
SPACE = re.compile(r"\s+")
TRUNCATED = " [truncated]"


def untrusted_text(value: str | None, limit: int = 2000) -> str:
    if not value:
        return ""
    text = TAG.sub(" ", value)
    text = ANGLE.sub(" ", text)
    text = CONTROL.sub("", text)
    text = SPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - len(TRUNCATED)].rstrip() + TRUNCATED
    return text
