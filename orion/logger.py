"""Central logging for Orion Elite — console + rotating file."""
from __future__ import annotations

import logging
import sys
import warnings
from logging.handlers import RotatingFileHandler

import config

# sounddevice 0.5.x assigns to ndarray.shape internally; NumPy 2.5 warns.
# That warning is from the dependency, not Orion — keep the console readable.
warnings.filterwarnings(
    "ignore",
    message="Setting the shape on a NumPy array has been deprecated",
    category=DeprecationWarning,
)

# Windows consoles default to cp1252; force UTF-8 so emoji/rich logs never crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

_LOGGER: logging.Logger | None = None


def get_logger(name: str = "orion") -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("orion")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        fh = RotatingFileHandler(
            config.LOG_FILE, maxBytes=512_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass  # read-only location: console logging still works

    _LOGGER = logger
    return logger


log = get_logger()
