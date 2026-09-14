"""Common health contract for external integrations."""

from typing import Any, Protocol


class ExternalIntegration(Protocol):
    name: str

    async def health(self) -> dict[str, Any]: ...
