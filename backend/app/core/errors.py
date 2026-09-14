"""Application exceptions and the canonical API error envelope."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    def __init__(self, *, code: str, message: str, status_code: int = 400, details: Any = None,
                 retryable: bool = False, headers: dict[str, str] | None = None,
                 field_errors: list[dict[str, Any]] | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.retryable = retryable
        self.headers = headers
        self.field_errors = field_errors
        super().__init__(message)


class ProviderUnavailableError(ApplicationError):
    def __init__(self, provider: str, chain: str) -> None:
        super().__init__(
            code="PROVIDER_UNAVAILABLE",
            message=f"Blockchain data provider is unavailable for {chain}",
            status_code=503,
            details={"provider": provider, "chain": chain, "coverage": "unavailable"},
            retryable=True,
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _payload(request: Request, *, code: str, message: str, details: Any = None,
             retryable: bool = False, field_errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "details": details,
        "request_id": _request_id(request),
        "retryable": retryable,
    }
    if field_errors is not None:
        error["field_errors"] = field_errors
    return {"error": error}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(request, code=exc.code, message=exc.message, details=exc.details,
                             retryable=exc.retryable, field_errors=exc.field_errors),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part not in {"body", "query", "path"}),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_payload(request, code="VALIDATION_ERROR", message="Request validation failed",
                             field_errors=field_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_by_status = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT"}
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        details = None if isinstance(exc.detail, str) else exc.detail
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(request, code=code_by_status.get(exc.status_code, "HTTP_ERROR"), message=message,
                             details=details, retryable=exc.status_code in {429, 502, 503, 504}),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request failure", extra={"request_id": _request_id(request)})
        return JSONResponse(
            status_code=500,
            content=_payload(request, code="INTERNAL_ERROR", message="An unexpected error occurred"),
        )
