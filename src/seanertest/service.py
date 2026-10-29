# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Service handles, which tests receive through the ``services`` fixture."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from seanertest.kubernetes.cluster import Cluster


class Service:
    """Runtime handle exposed to pytest through the services fixture."""

    name: str

    def exec(self, command: str | list[str]) -> str:
        raise NotImplementedError


class ContainerService(Service):
    """A service that runs its own image in one pod."""

    def __init__(self, *, name: str, cluster: Cluster, namespace: str, pod: str, address: str, node_ports: dict[int, int]):
        self.name = name
        self.cluster = cluster
        self.namespace = namespace
        self.pod = pod
        self.address = address
        self._node_ports = node_ports

    def host_port(self, container_port: int) -> int:
        """The port on ``address`` that reaches ``container_port`` of the service."""
        try:
            return self._node_ports[container_port]
        except KeyError as error:
            raise KeyError(f"service {self.name!r} does not publish TCP port {container_port}") from error

    def endpoint(self, container_port: int, scheme: str = "http") -> str:
        return f"{scheme}://{self.address}:{self.host_port(container_port)}"

    def logs(self) -> str:
        return self.cluster.logs(self.namespace, self.pod)

    def exec(self, command: str | list[str]) -> str:
        argv = ["/bin/sh", "-c", command] if isinstance(command, str) else list(command)
        result = self.cluster.exec(self.namespace, self.pod, argv)
        if result.returncode != 0:
            raise RuntimeError(
                f"command {command!r} failed in service {self.name!r} with exit code {result.returncode}\n"
                f"{result.stdout}{result.stderr}"
            )
        return result.stdout


class Services(Mapping[str, Service]):
    def __init__(self, values: dict[str, Service]):
        self._values = values

    def __getitem__(self, key: str) -> Service:
        try:
            return self._values[key]
        except KeyError as error:
            available = ", ".join(sorted(self._values)) or "<none>"
            raise KeyError(f"unknown service {key!r}; available services: {available}") from error

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)
