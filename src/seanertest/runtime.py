from __future__ import annotations

import io
import os
import shlex
import socket
import tarfile
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import docker
from docker.models.containers import Container
from docker.models.networks import Network

from .spec import FileSpec, FixtureSpec, ServiceSpec

_CONFIG_PATH = "/tmp/seanertest/config.yml"


@dataclass
class Service:
    name: str
    container: Container
    access_host: str
    activate: str | None = None

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
            diagnostics = _exit_diagnostics(self.container, result.exit_code)
            raise RuntimeError(
                f"command {command!r} failed in service {self.name!r} "
                f"with exit code {result.exit_code}\n{output}{diagnostics}"
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

            expected = {service.name for service in self.spec.services}
            actual = set(self.services)
            if actual != expected:
                raise RuntimeError(
                    f"internal service mismatch: expected {sorted(expected)!r}, "
                    f"got {sorted(actual)!r}"
                )

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

        files = list(spec.files)
        if spec.config is not None:
            files.append(FileSpec(source=spec.config, target=_CONFIG_PATH))
        if files:
            _copy_files(container, files)

        container.start()
        _wait_for_container_running(container, spec.name, self.startup_timeout)
        _run_setup(container, spec)

        self.services[spec.name] = Service(
            name=spec.name,
            container=container,
            access_host=self.access_host,
            activate=spec.activate,
        )

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout

        for spec in self.spec.services:
            service = self.services[spec.name]

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


def _wait_for_container_running(container: Container, name: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        container.reload()
        state = container.attrs["State"]
        status = state.get("Status")
        if status == "running":
            return
        if status == "exited":
            logs = container.logs(stdout=True, stderr=True).decode(errors="replace")
            raise RuntimeError(f"service {name!r} exited during startup\n{logs}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"service {name!r} did not start")
        time.sleep(0.1)


def _run_setup(container: Container, spec: ServiceSpec) -> None:
    for command in spec.setup:
        result = container.exec_run(["/bin/sh", "-lc", command])
        output = result.output.decode(errors="replace")
        if result.exit_code != 0:
            diagnostics = _exit_diagnostics(container, result.exit_code)
            raise RuntimeError(
                f"setup command {command!r} failed in service {spec.name!r} "
                f"with exit code {result.exit_code}\n{output}{diagnostics}"
            )

    if spec.activate is not None:
        result = container.exec_run(["test", "-f", spec.activate])
        if result.exit_code != 0:
            raise RuntimeError(
                f"activation script {spec.activate!r} was not created "
                f"for service {spec.name!r}"
            )


def _exit_diagnostics(container: Container, exit_code: int) -> str:
    """Return extra diagnostics for processes killed with SIGKILL (137)."""
    if exit_code != 137:
        return ""

    lines = [
        "",
        "exit code 137 means the process was killed with SIGKILL.",
        "Container resource diagnostics:",
    ]

    try:
        container.reload()
        attrs = container.attrs
        host_config = attrs.get("HostConfig", {})
        state = attrs.get("State", {})
        lines.extend(
            [
                f"docker.memory={host_config.get('Memory', 0)}",
                f"docker.memory_swap={host_config.get('MemorySwap', 0)}",
                f"docker.nano_cpus={host_config.get('NanoCpus', 0)}",
                f"docker.pids_limit={host_config.get('PidsLimit', 0)}",
                f"docker.oom_killed={state.get('OOMKilled', False)}",
            ]
        )
    except Exception as exc:
        lines.append(f"docker.inspect_error={exc}")

    command = r"""
for path in \
    /sys/fs/cgroup/memory.max \
    /sys/fs/cgroup/memory.current \
    /sys/fs/cgroup/memory.events \
    /sys/fs/cgroup/memory.swap.max \
    /sys/fs/cgroup/memory.limit_in_bytes \
    /sys/fs/cgroup/memory.usage_in_bytes \
    /sys/fs/cgroup/memory.failcnt \
    /sys/fs/cgroup/memory.oom_control
do
    if [ -r "$path" ]; then
        echo "--- $path"
        cat "$path"
    fi
done

if [ -r /proc/meminfo ]; then
    echo "--- /proc/meminfo"
    grep -E '^(MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo || true
fi
"""

    try:
        result = container.exec_run(["/bin/sh", "-c", command])
        output = result.output.decode(errors="replace").strip()
        if output:
            lines.append(output)
    except Exception as exc:
        lines.append(f"cgroup.diagnostics_error={exc}")

    return "\n" + "\n".join(lines) + "\n"


def _copy_files(container: Container, files: list[FileSpec]) -> None:
    archive = io.BytesIO()
    directories: set[str] = set()

    with tarfile.open(fileobj=archive, mode="w") as tar:
        for file_spec in files:
            target = PurePosixPath(file_spec.target)
            relative_target = target.relative_to("/")

            parent = relative_target.parent
            parents = list(reversed(parent.parents)) + [parent]
            for directory_path in parents:
                directory_name = str(directory_path)
                if directory_name in (".", "") or directory_name in directories:
                    continue
                directory = tarfile.TarInfo(directory_name)
                directory.type = tarfile.DIRTYPE
                directory.mode = 0o755
                tar.addfile(directory)
                directories.add(directory_name)

            data = file_spec.source.read_bytes()
            info = tarfile.TarInfo(str(relative_target))
            info.size = len(data)
            info.mode = 0o755 if os.access(file_spec.source, os.X_OK) else 0o444
            tar.addfile(info, io.BytesIO(data))

    if not container.put_archive("/", archive.getvalue()):
        raise RuntimeError("could not copy fixture files into service container")


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
