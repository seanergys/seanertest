# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Fixture files, version 2.

A fixture declares the logical nodes a test needs once, at fixture level, and
then the services. A node service, such as Flux, runs on the logical nodes of
the roles it names and uses software built with Spack. A container service,
such as PostgreSQL, runs its own image as an ordinary pod.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from seanerops import NodeGroup, Request, RequestError
from seanerops.request import parse_groups
from seanerops.target import MODES

FIXTURE_NAME = "fixture.yaml"
NODE_DRIVERS = ("flux", "environment")
CONTAINER_DRIVERS = ("container",)


class FixtureError(ValueError):
    pass


@dataclass(frozen=True)
class SpackEnvironment:
    """A Spack environment, identified by the content of its spack.yaml."""

    source: Path
    content: bytes

    @property
    def id(self) -> str:
        return hashlib.sha256(self.content).hexdigest()[:16]


@dataclass(frozen=True)
class FileSpec:
    source: Path
    target: str


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    driver: str
    # Node services.
    roles: tuple[str, ...] = ()
    config: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)
    # Container services.
    image: str | None = None
    command: tuple[str, ...] | None = None
    entrypoint: tuple[str, ...] | None = None
    environment: dict[str, str] = field(default_factory=dict)
    ports: tuple[int, ...] = ()
    files: tuple[FileSpec, ...] = ()
    setup: tuple[str, ...] = ()

    @property
    def runs_on_nodes(self) -> bool:
        return self.driver in NODE_DRIVERS


@dataclass(frozen=True)
class FixtureSpec:
    path: Path
    groups: tuple[NodeGroup, ...]
    mode: str | None
    software: SpackEnvironment | None
    services: tuple[ServiceSpec, ...]

    @property
    def request(self) -> Request | None:
        """The node request of this fixture, or None if it needs no nodes."""
        if not self.groups:
            return None
        return Request(groups=self.groups, mode=self.mode)


def load_fixture(path: Path) -> FixtureSpec:
    path = path.resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    where = str(path)
    if not isinstance(data, dict):
        raise FixtureError(f"{where}: fixture must be a mapping")
    _known(data, {"version", "allocation", "nodes", "services"}, where)
    if data.get("version") != 2:
        raise FixtureError(f"{where}: only fixture version 2 is supported")

    groups: tuple[NodeGroup, ...] = ()
    if data.get("nodes") is not None:
        try:
            groups = parse_groups(data["nodes"], f"{where}: nodes")
        except RequestError as error:
            raise FixtureError(str(error)) from error

    mode = None
    if data.get("allocation") is not None:
        allocation = data["allocation"]
        if not isinstance(allocation, dict) or set(allocation) != {"mode"} or allocation["mode"] not in MODES:
            raise FixtureError(f"{where}: allocation must be {{mode: shared|exclusive}}")
        mode = allocation["mode"]

    raw_services = data.get("services")
    if not isinstance(raw_services, list) or not raw_services:
        raise FixtureError(f"{where}: services must be a non-empty list")

    services: list[ServiceSpec] = []
    environments: set[SpackEnvironment] = set()
    roles = {group.role for group in groups}
    for index, raw in enumerate(raw_services):
        service_where = f"{where}: services[{index}]"
        if not isinstance(raw, dict):
            raise FixtureError(f"{service_where} must be a mapping")
        name = _string(raw, "name", service_where)
        if any(service.name == name for service in services):
            raise FixtureError(f"{service_where}: service {name!r} is listed twice")
        driver = _string(raw, "driver", service_where)
        if driver in NODE_DRIVERS:
            service, environment = _node_service(path, raw, name, driver, roles, service_where)
            environments.add(environment)
        elif driver in CONTAINER_DRIVERS:
            service = _container_service(path, raw, name, driver, service_where)
        else:
            raise FixtureError(
                f"{service_where}: unknown driver {driver!r}; expected one of "
                f"{', '.join(NODE_DRIVERS + CONTAINER_DRIVERS)}"
            )
        services.append(service)

    if len(environments) > 1:
        raise FixtureError(f"{where}: node services share the logical nodes, so they must use the same spack.yaml")
    if environments and not groups:
        raise FixtureError(f"{where}: node services need a nodes block")

    return FixtureSpec(
        path=path,
        groups=groups,
        mode=mode,
        software=next(iter(environments), None),
        services=tuple(services),
    )


def _node_service(path, raw, name, driver, roles, where) -> tuple[ServiceSpec, SpackEnvironment]:
    known = {"name", "driver", "roles", "software", "config", "options"}
    _known(raw, known, where)
    service_roles = raw.get("roles")
    if not isinstance(service_roles, list) or not service_roles or not all(isinstance(r, str) for r in service_roles):
        raise FixtureError(f"{where}: roles must be a non-empty list of role names")
    unknown = [role for role in service_roles if role not in roles]
    if unknown:
        raise FixtureError(f"{where}: roles not declared in nodes: {', '.join(unknown)}")
    software = raw.get("software")
    if not isinstance(software, dict) or set(software) != {"spack"}:
        raise FixtureError(f"{where}: software must be {{spack: spack.yaml}}")
    spack_yaml = _local_file(path, _string(software, "spack", f"{where}: software"), f"{where}: software.spack")
    config = None
    if raw.get("config") is not None:
        config = _local_file(path, _string(raw, "config", where), f"{where}: config")
    options = raw.get("options", {})
    if not isinstance(options, dict):
        raise FixtureError(f"{where}: options must be a mapping")
    service = ServiceSpec(name=name, driver=driver, roles=tuple(service_roles), config=config, options=options)
    return service, SpackEnvironment(source=spack_yaml, content=spack_yaml.read_bytes())


def _container_service(path, raw, name, driver, where) -> ServiceSpec:
    known = {"name", "driver", "image", "command", "entrypoint", "environment", "ports", "files", "setup", "config"}
    _known(raw, known, where)
    files = []
    for file_index, raw_file in enumerate(raw.get("files", [])):
        file_where = f"{where}: files[{file_index}]"
        if not isinstance(raw_file, dict):
            raise FixtureError(f"{file_where} must be a mapping")
        target = _absolute(_string(raw_file, "target", file_where), f"{file_where}: target")
        source = _local_file(path, _string(raw_file, "source", file_where), f"{file_where}: source")
        files.append(FileSpec(source=source, target=target))
    if raw.get("config") is not None:
        # The configuration file is mounted at a fixed path, which the service
        # finds through SEANERTEST_CONFIG.
        source = _local_file(path, _string(raw, "config", where), f"{where}: config")
        files.append(FileSpec(source=source, target=f"/etc/seanertest/{source.name}"))

    environment = raw.get("environment", {})
    if not isinstance(environment, dict):
        raise FixtureError(f"{where}: environment must be a mapping")
    environment = {str(key): str(value) for key, value in environment.items()}
    if raw.get("config") is not None:
        environment.setdefault("SEANERTEST_CONFIG", files[-1].target)

    ports = raw.get("ports", [])
    if not isinstance(ports, list) or not all(isinstance(p, int) and 1 <= p <= 65535 for p in ports):
        raise FixtureError(f"{where}: ports must be a list of TCP ports")
    setup = raw.get("setup", [])
    if not isinstance(setup, list) or not all(isinstance(command, str) and command.strip() for command in setup):
        raise FixtureError(f"{where}: setup must be a list of shell commands")

    return ServiceSpec(
        name=name,
        driver=driver,
        image=_string(raw, "image", where),
        command=_argv(raw.get("command"), f"{where}: command"),
        entrypoint=_argv(raw.get("entrypoint"), f"{where}: entrypoint"),
        environment=environment,
        ports=tuple(ports),
        files=tuple(files),
        setup=tuple(setup),
    )


def _argv(value: Any, where: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return ("/bin/sh", "-c", value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise FixtureError(f"{where} must be a string or a list of strings")


def _absolute(value: str, where: str) -> str:
    target = PurePosixPath(value)
    if not target.is_absolute() or target == PurePosixPath("/") or ".." in target.parts:
        raise FixtureError(f"{where} must be an absolute file path without '..'")
    return value


def _local_file(fixture_path: Path, value: str, where: str) -> Path:
    root = fixture_path.parent.resolve()
    source = (root / value).resolve()
    if not source.is_relative_to(root):
        raise FixtureError(f"{where} must stay inside the test directory")
    if not source.is_file():
        raise FixtureError(f"{where} does not exist: {value}")
    return source


def _known(value: dict, keys: set[str], where: str) -> None:
    unknown = set(value) - keys
    if unknown:
        raise FixtureError(f"{where}: unknown keys: {', '.join(sorted(map(str, unknown)))}")


def _string(value: dict, key: str, where: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise FixtureError(f"{where}: {key} must be a non-empty string")
    return item
