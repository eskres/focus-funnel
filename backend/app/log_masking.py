"""Mask API keys in log output, and keep query strings out of the access log.

Code that handles a key registers it for the current request context. A
wrapped log record factory masks every registered key in each record's message
and traceback when the record is created, so no handler or formatter (including
ones uvicorn adds later) ever sees the key.

The same factory drops the query string from the path of every uvicorn access
record: a filter value such as a tag is the user's own words, and would outlive
a delete in the operator's logs (thought-library design decision 4).
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


ACCESS_LOGGER = "uvicorn.access"


def _drop_query(record: logging.LogRecord) -> None:
    """Cut the path of a uvicorn access record at its first `?`.

    uvicorn's AccessFormatter unpacks exactly five args (client address,
    method, full path, HTTP version, status code), so only args[2] changes.
    """
    args = record.args
    if record.name == ACCESS_LOGGER and isinstance(args, tuple) and len(args) == 5:
        path = str(args[2])
        if "?" in path:
            record.args = (args[0], args[1], path.split("?", 1)[0], args[3], args[4])


def install_log_masking() -> None:
    """Wrap the log record factory once; safe to call more than once."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "masks_secrets", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        _drop_query(record)
        if _secrets.get():
            _mask_record(record)
        return record

    factory.masks_secrets = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


APP_LOGGER = "app"
APP_LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"


def configure_app_logging() -> None:
    """Let the backend's own `app.*` loggers write INFO lines to stderr
    (thought-export design decision 17).

    Sets only the `app` logger: root and library loggers keep their levels,
    so a library such as httpx logs no request URLs. The handler is added
    only when the `app` logger has none, so a second call adds nothing.
    `propagate` stays on, so pytest's caplog still sees the records.
    """
    logger = logging.getLogger(APP_LOGGER)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()  # stderr
        handler.setFormatter(logging.Formatter(APP_LOG_FORMAT))
        logger.addHandler(handler)
