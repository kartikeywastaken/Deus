"""Small, dependency-free logging setup for API and worker processes."""

import logging
from logging.config import dictConfig


def configure_logging(level: str = "INFO") -> None:
    """Configure consistent structured-ish console logging."""

    normalized_level = level.upper()
    if normalized_level not in logging.getLevelNamesMapping():
        normalized_level = "INFO"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {"handlers": ["console"], "level": normalized_level},
        }
    )
