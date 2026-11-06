"""Structured (JSON) logs that never carry names or phone numbers.

Masking happens when a log record is created (a LogRecord factory), so it covers every logger
and every handler, ours or a library's. Request logs record the route template and the member
id, never the raw path or query string, so a search for a name never reaches the log.
"""

import json
import logging
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

PHONE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Structured fields that may hold PHI: their values are never logged.
PHI_FIELDS = frozenset(
    {"name", "first_name", "last_name", "full_name", "dob", "phone", "number", "from_number", "q"}
)
STANDARD = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
WORD = re.compile(r"\b[A-Z][a-zA-Z'-]+\b")
QUERY_VALUE = re.compile(r"([?&][\w.-]+=)[^&\s\"']+")
# Member first and last names (lower case), loaded at startup: masked wherever they appear.
_names: set[str] = set()


def register_names(names: Iterable[str | None]) -> None:
    _names.update(n.lower() for n in names if n and len(n) >= 2)


def mask(text: str) -> str:
    text = QUERY_VALUE.sub(lambda m: m.group(1) + "[masked]", text)  # ?q=Raymond -> ?q=[masked]
    text = EMAIL.sub("[email]", PHONE.sub("[phone]", text))
    if _names:
        text = WORD.sub(lambda m: "[name]" if m.group().lower() in _names else m.group(), text)
    return text


def _masked(value: Any) -> Any:
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {k: "[masked]" if k in PHI_FIELDS else _masked(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_masked(v) for v in value]
    return value


_installed = False


def _install_masking_factory() -> None:
    global _installed
    if _installed:
        return
    original = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = original(*args, **kwargs)
        try:
            record.msg, record.args = mask(record.getMessage()), None
        except (TypeError, ValueError):  # a malformed format string: keep it, masked
            record.msg, record.args = mask(str(record.msg)), None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in STANDARD and not key.startswith("_"):
                entry[key] = "[masked]" if key in PHI_FIELDS else _masked(value)
        if record.exc_info:
            entry["error"] = mask(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent: JSON to stdout, masking on, uvicorn's access log (raw paths) silenced."""
    _install_masking_factory()
    root = logging.getLogger()
    if not any(getattr(h, "_casecompass", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._casecompass = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # we log requests ourselves
    for chatty in ("httpx", "httpx2", "httpcore", "httpcore2"):  # full URLs at INFO
        logging.getLogger(chatty).setLevel(logging.WARNING)
