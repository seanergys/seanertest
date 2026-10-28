# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""SEANERGYS integration tests on testbeds."""

from __future__ import annotations

from typing import Any

__version__ = "0.3.0"


def __getattr__(name: str) -> Any:
    # Importing seanertest stays light; the classes load on first use.
    if name == "FluxService":
        from seanertest.drivers.flux import FluxService

        return FluxService
    if name in {"Service", "Services", "ContainerService"}:
        from seanertest import service

        return getattr(service, name)
    raise AttributeError(name)


__all__ = ["ContainerService", "FluxService", "Service", "Services"]
