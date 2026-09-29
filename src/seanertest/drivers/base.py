# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from abc import ABC, abstractmethod

from seanertest.docker_backend import DockerBackend
from seanertest.machine import MachineAllocation
from seanertest.service import Service
from seanertest.spec import DriverVariantSpec, ServiceSpec


class ServiceDriver(ABC):
    name: str

    def __init__(
        self,
        *,
        backend: DockerBackend,
        machine: MachineAllocation,
        service_spec: ServiceSpec,
        variant: DriverVariantSpec,
        testbed: str,
    ):
        self.backend = backend
        self.machine = machine
        self.service_spec = service_spec
        self.variant = variant
        self.testbed = testbed

    @abstractmethod
    def start(self) -> Service:
        raise NotImplementedError

    def stop(self) -> None:
        pass
