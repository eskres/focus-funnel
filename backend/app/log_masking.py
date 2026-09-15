"""Mask API keys in log output.

Code that handles a key registers it for the current request context. A
wrapped log record factory masks every registered key in each record's message
and traceback when the record is created, so no handler or formatter (including
ones uvicorn adds later) ever sees the key.
"""

import logging
from contextvars import ContextVar

MASK = "[REDACTED]"
# Shorter values are too likely to match ordinary text.
MIN_SECRET_LENGTH = 8

_secrets: ContextVar[frozenset[str]] = ContextVar("secrets_to_mask", default=frozenset())
_formatter = logging.Formatter()


def register_secret(value: str) -> None:
    """Mask this value in logs for the rest of the current request context."""
    if len(value) >= MIN_SECRET_LENGTH:
        _secrets.set(_secrets.get() | {value})


def mask_secrets(text: str) -> str:
    for secret in _secrets.get():
        text = text.replace(secret, MASK)
    return text


def _mask_record(record: logging.LogRecord) -> None:
    try:
        message = record.getMessage()
    except Exception:
        # Leave malformed records for the handler to report as usual.
        return
    masked = mask_secrets(message)
    if masked != message:
        record.msg, record.args = masked, None
    if record.exc_info:
        record.exc_text = mask_secrets(_formatter.formatException(record.exc_info))
    if record.stack_info:
        record.stack_info = mask_secrets(record.stack_info)


def install_log_masking() -> None:
    """Wrap the log record factory once; safe to call more than once."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "masks_secrets", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if _secrets.get():
            _mask_record(record)
        return record

    factory.masks_secrets = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
