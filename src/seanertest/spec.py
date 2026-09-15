from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


@dataclass(frozen=True)
class FileSpec:
    source: Path
    target: str


@dataclass(frozen=True)
class DriverVariantSpec:
    config: Path
    hosts: Path


@dataclass(frozen=True)
class DriverSpec:
    name: str
    config: dict[str, DriverVariantSpec]

    def select(self, testbed: str) -> DriverVariantSpec:
        if testbed in self.config:
            return self.config[testbed]
        try:
            return self.config["generic"]
        except KeyError as exc:
            available = ", ".join(sorted(self.config)) or "<none>"
            raise KeyError(
                f"driver {self.name!r} has no configuration for testbed {testbed!r} "
                f"and no generic fallback; available: {available}"
            ) from exc


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    driver: DriverSpec | None = None

    # Legacy single-container service fields. These remain useful for simple
    # component fixtures and keep existing SeanerTest fixtures working.
    image: str | None = None
    config: Path | None = None
    files: list[FileSpec] = field(default_factory=list)
    setup: list[str] = field(default_factory=list)
    activate: str | None = None
    command: str | list[str] | None = None
    entrypoint: str | list[str] | None = None
    environment: dict[str, str] = field(default_factory=dict)
    ports: list[int] = field(default_factory=list)

    @property
    def is_driver_service(self) -> bool:
        return self.driver is not None


@dataclass(frozen=True)
class FixtureSpec:
    path: Path
    services: list[ServiceSpec]

    @property
    def requires_machine(self) -> bool:
        return any(service.is_driver_service for service in self.services)

    @property
    def testbeds(self) -> tuple[str, ...]:
        values: set[str] = set()
        for service in self.services:
            if service.driver is not None:
                values.update(k for k in service.driver.config if k != "generic")
        return tuple(sorted(values))


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
        if name in names:
            raise ValueError(f"{where}: duplicate service name {name!r}")
        names.add(name)

        driver = _load_driver(path, raw.get("driver"), where)
        image_value = raw.get("image")
        image: str | None = None
        if image_value is not None:
            image = _required_string(raw, "image", where)

        if driver is not None:
            if image is not None:
                raise ValueError(
                    f"{where}: driver-backed services use the machine provider image; "
                    "do not set image"
                )
            extra = set(raw) - {"name", "driver"}
            if extra:
                raise ValueError(
                    f"{where}: driver-backed service has unsupported keys: "
                    f"{', '.join(sorted(extra))}"
                )
            services.append(ServiceSpec(name=name, driver=driver))
            continue

        if image is None:
            raise ValueError(f"{where}: image is required when driver is not set")

        config: Path | None = None
        if raw.get("config") is not None:
            config_value = _required_string(raw, "config", where)
            config = _local_file(path, config_value, f"{where}: config")

        files: list[FileSpec] = []
        raw_files = raw.get("files", [])
        if not isinstance(raw_files, list):
            raise ValueError(f"{where}: files must be a list")
        for file_index, raw_file in enumerate(raw_files):
            file_where = f"{where}: files[{file_index}]"
            if not isinstance(raw_file, dict):
                raise ValueError(f"{file_where}: file must be a mapping")
            source_value = _required_string(raw_file, "source", file_where)
            target = _required_string(raw_file, "target", file_where)
            target_path = PurePosixPath(target)
            if not target_path.is_absolute() or target_path == PurePosixPath("/"):
                raise ValueError(f"{file_where}: target must be an absolute file path")
            if ".." in target_path.parts:
                raise ValueError(f"{file_where}: target must not contain '..'")
            files.append(
                FileSpec(
                    source=_local_file(path, source_value, f"{file_where}: source"),
                    target=target,
                )
            )

        setup = raw.get("setup", [])
        if not isinstance(setup, list) or not all(
            isinstance(x, str) and x.strip() for x in setup
        ):
            raise ValueError(f"{where}: setup must be a list of non-empty shell commands")

        activate: str | None = None
        if raw.get("activate") is not None:
            activate = _required_string(raw, "activate", where)
            activate_path = PurePosixPath(activate)
            if not activate_path.is_absolute() or activate_path == PurePosixPath("/"):
                raise ValueError(f"{where}: activate must be an absolute file path")
            if ".." in activate_path.parts:
                raise ValueError(f"{where}: activate must not contain '..'")

        command = raw.get("command")
        if command is not None and not isinstance(command, (str, list)):
            raise ValueError(f"{where}: command must be a string or list")
        if isinstance(command, list) and not all(isinstance(x, str) for x in command):
            raise ValueError(f"{where}: command list entries must be strings")

        entrypoint = raw.get("entrypoint")
        if entrypoint is not None and not isinstance(entrypoint, (str, list)):
            raise ValueError(f"{where}: entrypoint must be a string or list")
        if isinstance(entrypoint, list) and not all(isinstance(x, str) for x in entrypoint):
            raise ValueError(f"{where}: entrypoint list entries must be strings")

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
                files=files,
                setup=list(setup),
                activate=activate,
                command=command,
                entrypoint=entrypoint,
                environment=environment,
                ports=ports,
            )
        )

    return FixtureSpec(path=path, services=services)


def _load_driver(path: Path, raw: object, where: str) -> DriverSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: driver must be a mapping")

    name = _required_string(raw, "name", f"{where}: driver")
    raw_config = raw.get("config")
    if not isinstance(raw_config, dict) or not raw_config:
        raise ValueError(f"{where}: driver.config must be a non-empty mapping")

    variants: dict[str, DriverVariantSpec] = {}
    for testbed, raw_variant in raw_config.items():
        variant_where = f"{where}: driver.config[{testbed!r}]"
        if not isinstance(testbed, str) or not testbed.strip():
            raise ValueError(f"{where}: driver.config keys must be non-empty strings")
        if not isinstance(raw_variant, dict):
            raise ValueError(f"{variant_where}: must be a mapping")
        config_value = _required_string(raw_variant, "config", variant_where)
        hosts_value = _required_string(raw_variant, "hosts", variant_where)
        variants[testbed] = DriverVariantSpec(
            config=_local_file(path, config_value, f"{variant_where}: config"),
            hosts=_local_file(path, hosts_value, f"{variant_where}: hosts"),
        )

    return DriverSpec(name=name, config=variants)


def _local_file(fixture_path: Path, value: str, where: str) -> Path:
    root = fixture_path.parent.resolve()
    source = (root / value).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{where} must stay inside the test directory") from exc
    if not source.is_file():
        raise ValueError(f"{where} does not exist: {value}")
    return source


def _required_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key} must be a non-empty string")
    return value
