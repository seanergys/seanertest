# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from seanertest.drivers.base import ServiceDriver


def get_driver(name: str) -> type[ServiceDriver]:
    if name == "flux":
        from seanertest.drivers.flux import FluxDriver

        return FluxDriver
    if name == "environment":
        from seanertest.drivers.environment import EnvironmentDriver

        return EnvironmentDriver
    raise KeyError(f"unknown node service driver {name!r}")
