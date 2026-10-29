# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from seanertest.fixture import ServiceSpec
from seanertest.kubernetes.cluster import Cluster
from seanertest.kubernetes.node import PodNode
from seanertest.service import Service


@dataclass(frozen=True)
class DriverContext:
    """What a driver gets from the generic layer."""

    cluster: Cluster
    namespace: str
    testbed: str
    nodes: dict[str, tuple[PodNode, ...]]
    startup_timeout: float = 120.0


class ServiceDriver(ABC):
    """Starts one service.

    The generic layer has already created the pods and installed the software.
    A driver only renders configuration, starts processes, checks readiness and
    returns the handle that tests use.
    """

    name: str

    def __init__(self, spec: ServiceSpec, context: DriverContext):
        self.spec = spec
        self.context = context

    @abstractmethod
    def start(self) -> Service:
        raise NotImplementedError

    def stop(self) -> None:
        pass
