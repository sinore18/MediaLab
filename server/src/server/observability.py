import contextvars
import logging
from collections.abc import Mapping
from pathlib import Path

from server.config import Settings

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_production_mode = False
LOG_DIRECTORY = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIRECTORY / "server.log"


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        return True


def configure_logging(settings: Settings) -> None:
    global _production_mode
    _production_mode = settings.prod
    level = logging.CRITICAL if settings.prod else logging.INFO
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s")
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("server")
    logger.setLevel(level)
    logger.propagate = False
    console_handler = next(
        (handler for handler in logger.handlers if getattr(handler, "_bleeper_console", False)),
        None,
    )
    if console_handler is None:
        handler = logging.StreamHandler()
        handler._bleeper_console = True
        logger.addHandler(handler)
        console_handler = handler
    _configure_handler(console_handler, formatter, level)
    _add_file_handler(logger, formatter, level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    _add_file_handler(root_logger, formatter, level)
    logging.getLogger("numba").setLevel(logging.WARNING)
    logging.getLogger("server.services.processing.pipeline").setLevel(logging.WARNING)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.setLevel(level)
    uvicorn_logger.propagate = True
    error_logger = logging.getLogger("uvicorn.error")
    error_logger.setLevel(level)
    error_logger.propagate = True
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.CRITICAL if settings.prod else logging.INFO)
    access_logger.propagate = True


def _configure_handler(handler: logging.Handler, formatter: logging.Formatter, level: int) -> None:
    handler.setLevel(level)
    handler.setFormatter(formatter)
    if not any(isinstance(log_filter, _RequestIdFilter) for log_filter in handler.filters):
        handler.addFilter(_RequestIdFilter())


def _add_file_handler(logger: logging.Logger, formatter: logging.Formatter, level: int) -> None:
    file_handler = next(
        (handler for handler in logger.handlers if getattr(handler, "_bleeper_log_file", None) == str(LOG_FILE)),
        None,
    )
    if file_handler is None:
        file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
        file_handler._bleeper_log_file = str(LOG_FILE)
        logger.addHandler(file_handler)
    _configure_handler(file_handler, formatter, level)


def set_request_id(request_id: str) -> contextvars.Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id.reset(token)


def log_exception(
    logger: logging.Logger,
    message: str,
    *args: object,
    context: Mapping[str, object] | None = None,
) -> None:
    logger.log(
        logging.CRITICAL if _production_mode else logging.ERROR,
        message,
        *args,
        extra=dict(context or {}),
        exc_info=True,
    )