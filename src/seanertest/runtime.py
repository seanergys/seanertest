from __future__ import annotations

import io
import os
import socket
import tarfile
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import docker
from docker.models.containers import Container
from docker.models.networks import Network

from .spec import FixtureSpec, ServiceSpec

_CONFIG_PATH = "/tmp/seanertest/config.yml"


@dataclass
class Service:
    name: str
    container: Container
    access_host: str

    def host_port(self, container_port: int) -> int:
        self.container.reload()
        key = f"{container_port}/tcp"
        bindings = self.container.attrs["NetworkSettings"]["Ports"].get(key)
        if not bindings:
            raise KeyError(f"service {self.name!r} does not publish TCP port {container_port}")
        return int(bindings[0]["HostPort"])

    def endpoint(self, container_port: int, scheme: str = "http") -> str:
        return f"{scheme}://{self.access_host}:{self.host_port(container_port)}"

    def logs(self) -> str:
        return self.container.logs(stdout=True, stderr=True).decode(errors="replace")

    def exec(self, command: str | list[str]) -> str:
        result = self.container.exec_run(command)
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
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class DockerFixtureEnvironment:
    def __init__(self, spec: FixtureSpec, startup_timeout: float = 30.0):
        self.spec = spec
        self.startup_timeout = startup_timeout
        self.client = docker.from_env()
        self.network: Network | None = None
        self.containers: list[Container] = []
        self.services: dict[str, Service] = {}
        self.run_id = uuid.uuid4().hex[:10]
        self.access_host = _docker_access_host()

    def start(self) -> Services:
        self.client.ping()
        _login_to_gitlab_registry(self.client)
        self.network = self.client.networks.create(
            f"seanertest-{self.run_id}",
            driver="bridge",
            labels={"org.seanergys.seanertest": "1"},
        )

        try:
            for service_spec in self.spec.services:
                self._start_service(service_spec)
            self._wait_until_ready()
            return Services(dict(self.services))
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        for container in reversed(self.containers):
            try:
                container.remove(force=True)
            except Exception:
                pass
        self.containers.clear()
        self.services.clear()

        if self.network is not None:
            try:
                self.network.remove()
            except Exception:
                pass
            self.network = None

        try:
            self.client.close()
        except Exception:
            pass

    def _start_service(self, spec: ServiceSpec) -> None:
        try:
            self.client.images.get(spec.image)
        except docker.errors.ImageNotFound:
            self.client.images.pull(spec.image)

        environment = dict(spec.environment)
        if spec.config is not None:
            environment["SEANERTEST_CONFIG"] = _CONFIG_PATH

        published_ports = {f"{port}/tcp": None for port in spec.ports}
        container = self.client.containers.create(
            spec.image,
            name=f"seanertest-{self.run_id}-{spec.name}",
            command=spec.command,
            environment=environment,
            ports=published_ports or None,
            labels={
                "org.seanergys.seanertest": "1",
                "org.seanergys.seanertest.service": spec.name,
            },
            detach=True,
        )
        self.containers.append(container)

        assert self.network is not None
        self.network.connect(container, aliases=[spec.name])

        if spec.config is not None:
            _copy_config(container, spec.config)

        container.start()
        self.services[spec.name] = Service(
            name=spec.name,
            container=container,
            access_host=self.access_host,
        )

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout

        for spec in self.spec.services:
            service = self.services[spec.name]

            while True:
                service.container.reload()
                state = service.container.attrs["State"]
                status = state.get("Status")
                if status == "exited":
                    raise RuntimeError(
                        f"service {spec.name!r} exited during startup\n{service.logs()}"
                    )
                if status == "running":
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"service {spec.name!r} did not start")
                time.sleep(0.1)

            for port in spec.ports:
                while True:
                    try:
                        host_port = service.host_port(port)
                        with socket.create_connection(
                            (service.access_host, host_port), timeout=0.5
                        ):
                            break
                    except (OSError, KeyError):
                        service.container.reload()
                        state = service.container.attrs["State"]
                        if state.get("Status") == "exited":
                            raise RuntimeError(
                                f"service {spec.name!r} exited during startup\n{service.logs()}"
                            )
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                f"service {spec.name!r} did not open TCP port {port}\n"
                                f"{service.logs()}"
                            )
                        time.sleep(0.2)


def _copy_config(container: Container, source: Path) -> None:
    data = source.read_bytes()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        directory = tarfile.TarInfo("seanertest")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        tar.addfile(directory)

        info = tarfile.TarInfo("seanertest/config.yml")
        info.size = len(data)
        info.mode = 0o444
        tar.addfile(info, io.BytesIO(data))

    if not container.put_archive("/tmp", archive.getvalue()):
        raise RuntimeError(f"could not copy config file {source} into service container")


def _docker_access_host() -> str:
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith(("tcp://", "http://", "https://")):
        parsed = urlparse(docker_host.replace("tcp://", "http://", 1))
        if parsed.hostname:
            return parsed.hostname
    return "127.0.0.1"


def _login_to_gitlab_registry(client: docker.DockerClient) -> None:
    registry = os.environ.get("CI_REGISTRY")
    username = os.environ.get("CI_REGISTRY_USER")
    password = os.environ.get("CI_REGISTRY_PASSWORD")
    if registry and username and password:
        client.login(username=username, password=password, registry=registry)
