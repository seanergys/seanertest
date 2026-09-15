from __future__ import annotations

from docker.models.containers import Container

from .docker_backend import DockerBackend
from .drivers import get_driver
from .drivers.base import ServiceDriver
from .machine import MachineAllocation, MachineSpec
from .service import ContainerService, Service, Services
from .spec import FixtureSpec, ServiceSpec


class FixtureEnvironment:
    """Materialize a fixture on a selected machine/testbed."""

    def __init__(
        self,
        spec: FixtureSpec,
        *,
        machine_spec: MachineSpec | None = None,
        testbed: str | None = None,
        startup_timeout: float = 30.0,
    ):
        self.spec = spec
        self.machine_spec = machine_spec
        self.testbed = testbed
        self.backend = DockerBackend(startup_timeout=startup_timeout)
        self.machine: MachineAllocation | None = None
        self.services: dict[str, Service] = {}
        self.drivers: list[ServiceDriver] = []

    def start(self) -> Services:
        if self.spec.requires_machine:
            if self.machine_spec is None or self.testbed is None:
                raise ValueError(
                    "fixture contains driver-backed services; a testbed/machine "
                    "must be selected"
                )
            if self.machine_spec.name != self.testbed:
                raise ValueError(
                    f"selected testbed {self.testbed!r} loaded machine "
                    f"{self.machine_spec.name!r}"
                )

        self.backend.start()
        try:
            if self.machine_spec is not None:
                self.machine = self.backend.provision_machine(self.machine_spec)

            legacy_services: list[tuple[ServiceSpec, Container]] = []
            for service_spec in self.spec.services:
                if service_spec.driver is not None:
                    self._start_driver_service(service_spec)
                else:
                    container = self.backend.start_container_service(service_spec)
                    service = ContainerService(
                        name=service_spec.name,
                        container=container,
                        access_host=self.backend.access_host,
                        activate=service_spec.activate,
                    )
                    self.services[service_spec.name] = service
                    legacy_services.append((service_spec, container))

            self.backend.wait_for_ports(legacy_services)

            expected = {service.name for service in self.spec.services}
            actual = set(self.services)
            if actual != expected:
                raise RuntimeError(
                    f"fixture service mismatch: expected {sorted(expected)!r}, "
                    f"got {sorted(actual)!r}"
                )
            return Services(dict(self.services))
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        for driver in reversed(self.drivers):
            try:
                driver.stop()
            except Exception:
                pass
        self.drivers.clear()
        self.services.clear()
        self.machine = None
        self.backend.stop()

    def _start_driver_service(self, service_spec: ServiceSpec) -> None:
        if self.machine is None or self.testbed is None or service_spec.driver is None:
            raise RuntimeError("driver-backed service has no provisioned machine")

        variant = service_spec.driver.select(self.testbed)
        driver_class = get_driver(service_spec.driver.name)
        driver = driver_class(
            backend=self.backend,
            machine=self.machine,
            service_spec=service_spec,
            variant=variant,
            testbed=self.testbed,
        )
        self.drivers.append(driver)
        self.services[service_spec.name] = driver.start()


# Compatibility alias for code that imported the original prototype name.
DockerFixtureEnvironment = FixtureEnvironment
