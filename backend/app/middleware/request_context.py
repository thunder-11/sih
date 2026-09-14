"""Request and correlation ID propagation."""

from contextvars import ContextVar
import logging
import re
from time import perf_counter
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.metrics import operational_metrics


request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
correlation_id_context: ContextVar[str | None] = ContextVar("correlation_id", default=None)
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger("sih26183.request")


def _safe_or_new(value: str | None) -> str:
    if value and SAFE_ID.fullmatch(value):
        return value
    return str(uuid.uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = _safe_or_new(request.headers.get("X-Request-ID"))
        correlation_id = _safe_or_new(request.headers.get("X-Correlation-ID") or request_id)
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        request_token = request_id_context.set(request_id)
        correlation_token = correlation_id_context.set(correlation_id)
        started = perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            logger.info(
                "%s %s %s %.2fms",
                request.method,
                request.url.path,
                response.status_code,
                (perf_counter() - started) * 1000,
                extra={"request_id": request_id, "correlation_id": correlation_id},
            )
            operational_metrics.record_request(response.status_code, (perf_counter() - started) * 1000)
            return response
        finally:
            request_id_context.reset(request_token)
            correlation_id_context.reset(correlation_token)
