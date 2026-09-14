"""Canonical response structures for new and migrated endpoints."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str
    retryable: bool = False
    field_errors: list[dict[str, Any]] | None = None


class StandardError(BaseModel):
    error: ErrorDetail


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
