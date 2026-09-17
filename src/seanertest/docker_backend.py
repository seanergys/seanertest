from __future__ import annotations

import hashlib
import io
import os
import socket
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import docker as docker_sdk
from docker.models.containers import Container
from docker.models.networks import Network

from .machine import MachineAllocation, MachineSpec
from .spec import FileSpec, ServiceSpec

_CONFIG_PATH = "/tmp/seanertest/config.yml"
_SPACK_ENV = "/opt/seanertest/spack-env"
_SPACK_ACTIVATE = "/opt/seanertest/spack-activate.sh"


@dataclass
class DockerNode:
    name: str
    hostname: str
    role: str
    container: Container
    activate: str | None = None

    def _activated_command(self, command: str | list[str]) -> str | list[str]:
        if self.activate is None:
            return command
        if isinstance(command, str):
            return ["/bin/sh", "-lc", f". {self.activate}\n{command}"]
        return [
            "/bin/sh",
            "-lc",
            f'. {self.activate}\nexec "$@"',
            "seanertest",
            *command,
        ]

    def exec(
        self,
        command: str | list[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> str:
        result = self.container.exec_run(
            self._activated_command(command), environment=environment
        )
        output = result.output.decode(errors="replace")
        if result.exit_code != 0:
            raise RuntimeError(
                f"command {command!r} failed on node {self.hostname!r} "
                f"with exit code {result.exit_code}\n{output}"
            )
        return output

    def exec_detached(
        self,
        command: str | list[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> None:
        self.container.exec_run(
            self._activated_command(command),
            environment=environment,
            detach=True,
        )

    def logs(self) -> str:
        return self.container.logs(stdout=True, stderr=True).decode(errors="replace")

    def put_bytes(
        self,
        target: str,
        data: bytes,
        mode: int = 0o444,
        *,
        uid: int = 0,
        gid: int = 0,
    ) -> None:
        copy_bytes(
            self.container,
            target,
            data,
            mode=mode,
            uid=uid,
            gid=gid,
        )

    def read_bytes(self, path: str) -> bytes:
        return read_bytes(self.container, path)


class DockerBackend:
    """One isolated Docker network for one SeanerTest fixture run."""

    def __init__(self, startup_timeout: float = 30.0):
        self.startup_timeout = startup_timeout
        self.client = docker_sdk.from_env()
        self.network: Network | None = None
        self.containers: list[Container] = []
        self.run_id = uuid.uuid4().hex[:10]
        self.access_host = _docker_access_host()

    def start(self) -> None:
        self.client.ping()
        _login_to_gitlab_registry(self.client)
        self.network = self.client.networks.create(
            f"seanertest-{self.run_id}",
            driver="bridge",
            labels={"org.seanergys.seanertest": "1"},
        )

    def stop(self) -> None:
        for container in reversed(self.containers):
            try:
                container.remove(force=True)
            except Exception:
                pass
        self.containers.clear()

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

    def provision_machine(
        self,
        spec: MachineSpec,
        *,
        spack: Path | None = None,
    ) -> MachineAllocation:
        image = spec.provider.image
        activate = None
        if spack is not None:
            image = self.prepare_spack_image(image, spack)
            activate = _SPACK_ACTIVATE
        self._ensure_image(image)
        nodes: list[DockerNode] = []
        machine_prefix = _hostname_part(spec.name)

        for group in spec.nodes:
            for index in range(group.count):
                hostname = f"{machine_prefix}-{_hostname_part(group.role)}-{index}"
                container = self.client.containers.create(
                    image,
                    name=f"seanertest-{self.run_id}-{hostname}",
                    hostname=hostname,
                    command=spec.provider.command,
                    entrypoint=[] if spack is not None else None,
                    environment=dict(spec.provider.environment),
                    labels={
                        "org.seanergys.seanertest": "1",
                        "org.seanergys.seanertest.machine": spec.name,
                        "org.seanergys.seanertest.role": group.role,
                    },
                    detach=True,
                )
                self.containers.append(container)
                self._connect(container, aliases=[hostname])
                container.start()
                _wait_for_container_running(container, hostname, self.startup_timeout)
                nodes.append(
                    DockerNode(
                        name=f"{group.role}-{index}",
                        hostname=hostname,
                        role=group.role,
                        container=container,
                        activate=activate,
                    )
                )

        return MachineAllocation(spec=spec, nodes=tuple(nodes))

    def start_container_service(self, spec: ServiceSpec) -> Container:
        assert spec.image is not None
        self._ensure_image(spec.image)

        environment = dict(spec.environment)
        if spec.config is not None:
            environment["SEANERTEST_CONFIG"] = _CONFIG_PATH

        published_ports = {f"{port}/tcp": None for port in spec.ports}
        container = self.client.containers.create(
            spec.image,
            name=f"seanertest-{self.run_id}-{_hostname_part(spec.name)}",
            command=spec.command,
            entrypoint=spec.entrypoint,
            environment=environment,
            ports=published_ports or None,
            labels={
                "org.seanergys.seanertest": "1",
                "org.seanergys.seanertest.service": spec.name,
            },
            detach=True,
        )
        self.containers.append(container)
        self._connect(container, aliases=[spec.name])

        files = list(spec.files)
        if spec.config is not None:
            files.append(FileSpec(source=spec.config, target=_CONFIG_PATH))
        if files:
            copy_files(container, files)

        container.start()
        _wait_for_container_running(container, spec.name, self.startup_timeout)
        _run_setup(container, spec)
        return container

    def wait_for_ports(self, services: list[tuple[ServiceSpec, Container]]) -> None:
        deadline = time.monotonic() + self.startup_timeout
        for spec, container in services:
            for port in spec.ports:
                while True:
                    container.reload()
                    key = f"{port}/tcp"
                    bindings = container.attrs["NetworkSettings"]["Ports"].get(key)
                    if bindings:
                        host_port = int(bindings[0]["HostPort"])
                        try:
                            with socket.create_connection(
                                (self.access_host, host_port), timeout=0.5
                            ):
                                break
                        except OSError:
                            pass
                    state = container.attrs["State"]
                    if state.get("Status") == "exited":
                        logs = container.logs(stdout=True, stderr=True).decode(
                            errors="replace"
                        )
                        raise RuntimeError(
                            f"service {spec.name!r} exited during startup\n{logs}"
                        )
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"service {spec.name!r} did not open TCP port {port}"
                        )
                    time.sleep(0.2)

    def prepare_spack_image(self, base_image: str, environment: Path) -> str:
        self._ensure_image(base_image)
        base = self.client.images.get(base_image)
        manifest = environment.read_bytes()
        digest = hashlib.sha256(
            base.id.encode() + b"\0" + manifest
        ).hexdigest()[:20]
        tag = f"seanertest-spack:{digest}"

        try:
            self.client.images.get(tag)
            return tag
        except docker_sdk.errors.ImageNotFound:
            pass

        dockerfile = f"""ARG BASE_IMAGE
FROM ${{BASE_IMAGE}}
COPY spack.yaml /tmp/seanertest-spack.yaml
RUN mkdir -p {_SPACK_ENV} \\
 && spack env create --dir {_SPACK_ENV} /tmp/seanertest-spack.yaml \\
 && spack -e {_SPACK_ENV} concretize \\
 && spack -e {_SPACK_ENV} install \\
 && spack env activate --sh {_SPACK_ENV} > {_SPACK_ACTIVATE} \\
 && rm -f /tmp/seanertest-spack.yaml
"""
        context = io.BytesIO()
        with tarfile.open(fileobj=context, mode="w") as archive:
            for name, payload in (
                ("Dockerfile", dockerfile.encode()),
                ("spack.yaml", manifest),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(payload))
        context.seek(0)

        try:
            self.client.images.build(
                fileobj=context,
                custom_context=True,
                tag=tag,
                rm=True,
                buildargs={"BASE_IMAGE": base_image},
            )
        except docker_sdk.errors.BuildError as exc:
            detail = "\n".join(
                str(item.get("stream") or item.get("error") or "").rstrip()
                for item in exc.build_log
                if isinstance(item, dict)
            ).strip()
            raise RuntimeError(
                f"Spack environment build failed for {environment}\n{detail}"
            ) from exc

        return tag

    def _ensure_image(self, image: str) -> None:
        try:
            self.client.images.get(image)
        except docker_sdk.errors.ImageNotFound:
            self.client.images.pull(image)

    def _connect(self, container: Container, aliases: list[str]) -> None:
        if self.network is None:
            raise RuntimeError("Docker backend has not been started")
        self.network.connect(container, aliases=aliases)


def copy_files(container: Container, files: list[FileSpec]) -> None:
    archive = io.BytesIO()
    directories: set[str] = set()

    with tarfile.open(fileobj=archive, mode="w") as tar:
        for file_spec in files:
            _add_tar_file(
                tar,
                directories,
                file_spec.target,
                file_spec.source.read_bytes(),
                0o755 if os.access(file_spec.source, os.X_OK) else 0o444,
            )

    if not container.put_archive("/", archive.getvalue()):
        raise RuntimeError("could not copy fixture files into container")


def copy_bytes(
    container: Container,
    target: str,
    data: bytes,
    mode: int = 0o444,
    *,
    uid: int = 0,
    gid: int = 0,
) -> None:
    archive = io.BytesIO()
    directories: set[str] = set()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        _add_tar_file(tar, directories, target, data, mode, uid=uid, gid=gid)
    if not container.put_archive("/", archive.getvalue()):
        raise RuntimeError(f"could not copy {target} into container")


def read_bytes(container: Container, path: str) -> bytes:
    stream, _ = container.get_archive(path)
    archive = io.BytesIO(b"".join(stream))
    with tarfile.open(fileobj=archive, mode="r") as tar:
        member = next((item for item in tar.getmembers() if item.isfile()), None)
        if member is None:
            raise RuntimeError(f"container archive for {path} did not contain a file")
        handle = tar.extractfile(member)
        if handle is None:
            raise RuntimeError(f"could not read {path} from container archive")
        return handle.read()


def _add_tar_file(
    tar: tarfile.TarFile,
    directories: set[str],
    target: str,
    data: bytes,
    mode: int,
    *,
    uid: int = 0,
    gid: int = 0,
) -> None:
    target_path = PurePosixPath(target)
    relative_target = target_path.relative_to("/")
    parent = relative_target.parent
    parents = list(reversed(parent.parents)) + [parent]
    for directory_path in parents:
        directory_name = str(directory_path)
        if directory_name in (".", "") or directory_name in directories:
            continue
        directory = tarfile.TarInfo(directory_name)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        directory.uid = uid
        directory.gid = gid
        tar.addfile(directory)
        directories.add(directory_name)

    info = tarfile.TarInfo(str(relative_target))
    info.size = len(data)
    info.mode = mode
    info.uid = uid
    info.gid = gid
    tar.addfile(info, io.BytesIO(data))


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
            raise RuntimeError(f"container {name!r} exited during startup\n{logs}")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"container {name!r} did not start")
        time.sleep(0.1)


def _run_setup(container: Container, spec: ServiceSpec) -> None:
    for command in spec.setup:
        result = container.exec_run(["/bin/sh", "-lc", command])
        output = result.output.decode(errors="replace")
        if result.exit_code != 0:
            raise RuntimeError(
                f"setup command {command!r} failed in service {spec.name!r} "
                f"with exit code {result.exit_code}\n{output}"
            )

    if spec.activate is not None:
        result = container.exec_run(["test", "-f", spec.activate])
        if result.exit_code != 0:
            raise RuntimeError(
                f"activation script {spec.activate!r} was not created "
                f"for service {spec.name!r}"
            )


def _hostname_part(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    normalized = "-".join(part for part in normalized.split("-") if part)
    if not normalized:
        raise ValueError(f"cannot derive Docker hostname from {value!r}")
    return normalized


def _docker_access_host() -> str:
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith(("tcp://", "http://", "https://")):
        parsed = urlparse(docker_host.replace("tcp://", "http://", 1))
        if parsed.hostname:
            return parsed.hostname
    return "127.0.0.1"


def _login_to_gitlab_registry(client: docker_sdk.DockerClient) -> None:
    registry = os.environ.get("CI_REGISTRY")
    username = os.environ.get("CI_REGISTRY_USER")
    password = os.environ.get("CI_REGISTRY_PASSWORD")
    if registry and username and password:
        client.login(username=username, password=password, registry=registry)
