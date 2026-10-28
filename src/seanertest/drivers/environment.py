# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Logical nodes with the installed Spack environment and no running service."""

from __future__ import annotations

from seanertest.drivers.base import ServiceDriver
from seanertest.service import Service


class EnvironmentService(Service):
    def __init__(self, name: str, nodes: tuple):
        self.name = name
        self._nodes = nodes

    def nodes(self) -> tuple:
        return self._nodes

    def exec(self, command: str | list[str]) -> str:
        """Run a command with the environment activated on the first node."""
        return self._nodes[0].exec(command)


class EnvironmentDriver(ServiceDriver):
    name = "environment"

    def start(self) -> EnvironmentService:
        if self.spec.options:
            raise ValueError("the environment driver takes no options")
        nodes = tuple(node for role in self.spec.roles for node in self.context.nodes[role])
        return EnvironmentService(self.spec.name, nodes)
