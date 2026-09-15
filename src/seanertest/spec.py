from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    image: str
    config: Path | None = None
    command: str | list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)
    ports: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class FixtureSpec:
    path: Path
    services: list[ServiceSpec]


def load_fixture(path: Path) -> FixtureSpec:
    path = path.resolve()
    data = yaml.safe_load(path.read_text())

    if not isinstance(data, dict):
        raise ValueError(f"{path}: fixture must be a YAML mapping")
    if data.get("version") != 1:
        raise ValueError(f"{path}: only fixture version 1 is supported")

    raw_services = data.get("services")
    if not isinstance(raw_services, list) or not raw_services:
        raise ValueError(f"{path}: services must be a non-empty list")

    services: list[ServiceSpec] = []
    names: set[str] = set()

    for index, raw in enumerate(raw_services):
        where = f"{path}: services[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: service must be a mapping")

        name = _required_string(raw, "name", where)
        image = _required_string(raw, "image", where)
        if name in names:
            raise ValueError(f"{where}: duplicate service name {name!r}")
        names.add(name)

        config: Path | None = None
        if raw.get("config") is not None:
            config_value = _required_string(raw, "config", where)
            config = (path.parent / config_value).resolve()
            try:
                config.relative_to(path.parent.resolve())
            except ValueError as exc:
                raise ValueError(f"{where}: config must stay inside the test directory") from exc
            if not config.is_file():
                raise ValueError(f"{where}: config file does not exist: {config_value}")

        command = raw.get("command")
        if command is not None and not isinstance(command, (str, list)):
            raise ValueError(f"{where}: command must be a string or list")
        if isinstance(command, list) and not all(isinstance(x, str) for x in command):
            raise ValueError(f"{where}: command list entries must be strings")

        environment = raw.get("environment", {})
        if not isinstance(environment, dict):
            raise ValueError(f"{where}: environment must be a mapping")
        environment = {str(k): str(v) for k, v in environment.items()}

        raw_ports = raw.get("ports", [])
        if not isinstance(raw_ports, list):
            raise ValueError(f"{where}: ports must be a list")
        ports: list[int] = []
        for port in raw_ports:
            if not isinstance(port, int) or not (1 <= port <= 65535):
                raise ValueError(f"{where}: invalid TCP port {port!r}")
            ports.append(port)

        services.append(
            ServiceSpec(
                name=name,
                image=image,
                config=config,
                command=command,
                environment=environment,
                ports=ports,
            )
        )

    return FixtureSpec(path=path, services=services)


def _required_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key} must be a non-empty string")
    return value
