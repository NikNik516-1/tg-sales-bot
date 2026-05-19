import os
import logging
import structlog


def setup(service: str) -> structlog.BoundLogger:
    """Configure structlog once at startup. Returns a service-bound logger."""
    pretty = os.getenv("LOG_PRETTY", "").lower() in ("1", "true")

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if pretty:
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger().bind(service=service)
