"""
Structured JSON logging setup.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import config


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra_keys = {
            k: v for k, v in record.__dict__.items()
            if k not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
            )
        }
        if extra_keys:
            log_entry.update(extra_keys)
        if record.exc_info:
            log_entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging():
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    formatter = JsonFormatter()

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
