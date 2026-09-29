# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import shlex
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from docker.models.containers import Container


class Service:
    """Runtime handle exposed to pytest through the services fixture."""

    name: str

    def exec(self, command: str | list[str]) -> str:
        raise NotImplementedError

    def stop(self) -> None:
        pass


@dataclass
class ContainerService(Service):
    name: str
    container: Container
    access_host: str
    activate: str | None = None

    def host_port(self, container_port: int) -> int:
        self.container.reload()
        key = f"{container_port}/tcp"
        bindings = self.container.attrs["NetworkSettings"]["Ports"].get(key)
        if not bindings:
            raise KeyError(
                f"service {self.name!r} does not publish TCP port {container_port}"
            )
        return int(bindings[0]["HostPort"])

    def endpoint(self, container_port: int, scheme: str = "http") -> str:
        return f"{scheme}://{self.access_host}:{self.host_port(container_port)}"

    def logs(self) -> str:
        return self.container.logs(stdout=True, stderr=True).decode(errors="replace")

    def exec(self, command: str | list[str]) -> str:
        exec_command: str | list[str] = command
        if self.activate is not None:
            activate = shlex.quote(self.activate)
            if isinstance(command, str):
                exec_command = ["/bin/sh", "-lc", f". {activate} && {command}"]
            else:
                exec_command = [
                    "/bin/sh",
                    "-lc",
                    f'. {activate} && exec "$@"',
                    "seanertest",
                    *command,
                ]

        result = self.container.exec_run(exec_command)
        output = result.output.decode(errors="replace")
        if result.exit_code != 0:
            raise RuntimeError(
                f"command {command!r} failed in service {self.name!r} "
                f"with exit code {result.exit_code}\n{output}"
            )
        return output


class Services(Mapping[str, Service]):
    def __init__(self, values: dict[str, Service]):
        self._values = values

    def __getitem__(self, key: str) -> Service:
        try:
            return self._values[key]
        except KeyError as exc:
            available = ", ".join(sorted(self._values)) or "<none>"
            raise KeyError(
                f"unknown service {key!r}; available services: {available}"
            ) from exc

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)
