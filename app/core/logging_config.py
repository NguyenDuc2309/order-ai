import json
import logging
import os


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "logger": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "event") and isinstance(record.event, dict):
            payload["event"] = record.event
        return json.dumps(payload, ensure_ascii=False)


def setup_audit_logger() -> logging.Logger:
    logger = logging.getLogger("orderresolve.audit")
    if logger.handlers:
        return logger
    os.makedirs("logs", exist_ok=True)
    handler = logging.FileHandler("logs/audit.jsonl", encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
