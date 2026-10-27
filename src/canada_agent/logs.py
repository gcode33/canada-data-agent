"""JSON logs with a per-question trace id, and redaction of anything that looks like a secret."""

import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)

REDACTED = "[REDACTED]"
SECRET_KEYS = re.compile(r"authorization|api[-_]?key|token|secret|password", re.IGNORECASE)
SECRET_VALUES = re.compile(r"sk-ant-[A-Za-z0-9_\-]+|pa-[A-Za-z0-9_\-]{20,}|Bearer\s+\S+")

# Attributes every LogRecord has; anything else came from `extra=` and is logged.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


@contextmanager
def trace_id(value: str) -> Iterator[None]:
    token = _trace_id.set(value)
    try:
        yield
    finally:
        _trace_id.reset(token)


def redact(value: Any, key: str = "") -> Any:
    if key and SECRET_KEYS.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_VALUES.sub(REDACTED, value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": _trace_id.get(),
        }
        entry |= {k: v for k, v in vars(record).items() if k not in _STANDARD}
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(entry), default=str)


def configure_logging(level: int = logging.INFO, stream: IO[str] | None = None) -> None:
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("canada_agent")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False
