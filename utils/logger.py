"""
Logging Utility
===============
Configurable rotating file logger with color-coded Rich console output.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

import io
import sys
from rich.console import Console
from rich.logging import RichHandler


_logger: Optional[logging.Logger] = None

# Force UTF-8 output to avoid cp1252 encoding errors with emojis on Windows
try:
    _utf8_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    _console = Console(file=_utf8_stream, force_terminal=True)
except Exception:
    _console = Console()


def setup_logger(
    name: str = "optimizer",
    log_level: str = "INFO",
    log_file: str = "logs/optimizer.log",
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backup_count: int = 3,
) -> logging.Logger:
    """Initialize and return the application logger.

    Args:
        name: Logger name.
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        log_file: Path to the log file.
        max_bytes: Max size per log file before rotation.
        backup_count: Number of rotated log files to keep.

    Returns:
        Configured logging.Logger instance.
    """
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # ── Console handler (Rich) ──────────────────────────────────────────
    console_handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setLevel(logging.DEBUG)
    console_fmt = logging.Formatter("%(message)s", datefmt="[%X]")
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # ── File handler (rotating) ─────────────────────────────────────────
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Return the application logger, initializing with defaults if needed."""
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger
