"""Write backend logs to backend/logs/backend.log (and the terminal). Document text is never logged, only sizes."""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def setup_logging() -> None:
    root = logging.getLogger("app")
    if root.handlers or "pytest" in sys.modules:  # uvicorn --reload can import twice; tests should not write the log
        return
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file = RotatingFileHandler(LOG_DIR / "backend.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(file)
    root.addHandler(console)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
