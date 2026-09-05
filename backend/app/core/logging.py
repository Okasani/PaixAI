from __future__ import annotations

import logging

from app.core.security import redact, redact_text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        else:
            record.msg = redact(record.msg)
        if record.args:
            record.args = (
                tuple(redact(item) for item in record.args) if isinstance(record.args, tuple) else redact(record.args)
            )
        return True


def configure_redacted_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    redactor = RedactingFilter()
    for handler in root.handlers:
        handler.addFilter(redactor)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app"):
        logger = logging.getLogger(name)
        logger.addFilter(redactor)
        for handler in logger.handlers:
            handler.addFilter(redactor)
