import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in ("correlation_id", "worker_role", "probe_id", "event", "error_type"):
            value = getattr(record, name, None)
            if value is not None:
                fields[name] = value
        request_id = correlation_id.get()
        if request_id is not None:
            fields.setdefault("correlation_id", request_id)
        # Exceptions may contain credential-bearing URLs or connector response bodies.
        if record.exc_info:
            fields["error_type"] = record.exc_info[0].__name__
        return json.dumps(fields, ensure_ascii=False)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)

