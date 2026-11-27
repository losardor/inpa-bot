"""Process setup shared by every entry point: configuration and logging.

On a host with ``~/.config/tgbots/inpa-bot.env`` (the NUC) configuration
comes from there through tgkit, which refuses a file readable by others.
Without it (local development) the repo's ``.env`` is used, as before.

Logging goes through tgkit: bot tokens are redacted from every record, and
httpx (which logs request URLs that contain the token) is held at WARNING.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from tgkit import load_env, setup_logging
from tgkit.config import env_path

BOT_NAME = "inpa-bot"
REQUIRED = ("TELEGRAM_BOT_TOKEN", "DB_PATH")


def configure(logger_name: str = BOT_NAME) -> logging.Logger:
    """Load configuration and set up logging. Returns the named logger."""
    if env_path(BOT_NAME).is_file():
        load_env(BOT_NAME, required=REQUIRED)
    else:
        load_dotenv()

    log_dir = os.environ.get("LOG_DIR")
    setup_logging(BOT_NAME, Path(log_dir).expanduser() if log_dir else None)
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.getLogger().setLevel(getattr(logging, level_name, logging.INFO))

    db_path = os.environ.get("DB_PATH")
    if db_path and db_path != ":memory:":
        Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return logging.getLogger(logger_name)
