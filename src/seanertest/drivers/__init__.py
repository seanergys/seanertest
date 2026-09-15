from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import ServiceDriver


def get_driver(name: str) -> type[ServiceDriver]:
    if name == "flux":
        from .flux import FluxDriver

        return FluxDriver
    raise KeyError(f"unknown service driver {name!r}; available drivers: flux")


__all__ = ["get_driver"]
