import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from src.config import settings
from src.infrastructure.request_context import get_request_id

def add_request_id(
        _: Any,
        __: str,
        event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    event_dict["request_id"] = get_request_id()
    return event_dict

def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level.upper(),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_request_id,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )