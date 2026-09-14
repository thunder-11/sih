"""Canonical page calculations used by list endpoints."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageWindow:
    page: int = 1
    page_size: int = 25

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= self.page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_payload(items: list, total: int, window: PageWindow, **compatibility: object) -> dict:
    return {"items": items, "total": total, "page": window.page, "page_size": window.page_size, **compatibility}
