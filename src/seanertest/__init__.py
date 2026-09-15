"""SEANERGYS pytest service fixtures."""

from __future__ import annotations

from typing import Any

__version__ = "0.2.0"


def __getattr__(name: str) -> Any:
    # Keep importing seanertest lightweight for schema/config tooling while
    # preserving convenient runtime imports for tests.
    if name == "FluxService":
        from .drivers.flux import FluxService

        return FluxService
    if name in {"Service", "Services"}:
        from .service import Service, Services

        return {"Service": Service, "Services": Services}[name]
    raise AttributeError(name)


__all__ = ["FluxService", "Service", "Services"]
