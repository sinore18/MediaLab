import logging
from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response

from server.api.v1.router import api_router
from server.config import get_settings
from server.observability import configure_logging, reset_request_id, set_request_id

settings = get_settings()
configure_logging(settings)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Bleeper API",
    version="0.1.0",
    description="Secure video intake and profanity-cleanup processing API.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "x-ms-blob-type"],
    expose_headers=[
        "X-Bleep-Timestamps",
        "X-Bleep-Spans",
        "X-Video-Duration-Seconds",
    ],
)
app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(HTTPException)
async def log_http_exception(request: Request, error: HTTPException) -> Response:
    if error.status_code >= 500:
        logger.critical(
            "request failed method=%s path=%s status=%s reason=%s",
            request.method,
            request.url.path,
            error.status_code,
            error.detail,
        )
    elif not settings.prod:
        logger.warning(
            "request rejected method=%s path=%s status=%s reason=%s",
            request.method,
            request.url.path,
            error.status_code,
            error.detail,
        )
    return await http_exception_handler(request, error)


@app.exception_handler(RequestValidationError)
async def log_validation_exception(request: Request, error: RequestValidationError) -> Response:
    if not settings.prod:
        reasons = [
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()
        ]
        logger.warning(
            "request validation failed method=%s path=%s reasons=%s",
            request.method,
            request.url.path,
            reasons,
        )
    return await request_validation_exception_handler(request, error)


@app.middleware("http")
async def log_requests(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = uuid4().hex
    token = set_request_id(request_id)
    started_at = perf_counter()
    try:
        if not settings.prod:
            logger.debug("request started method=%s path=%s", request.method, request.url.path)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if response.status_code >= 500:
            logger.critical(
                "request failed method=%s path=%s status=%s",
                request.method,
                request.url.path,
                response.status_code,
            )
        elif not settings.prod:
            logger.debug(
                "request completed method=%s path=%s status=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                (perf_counter() - started_at) * 1000,
            )
        return response
    except Exception:
        logger.critical(
            "unhandled request exception method=%s path=%s",
            request.method,
            request.url.path,
            exc_info=True,
        )
        raise
    finally:
        reset_request_id(token)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}