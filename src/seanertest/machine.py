# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml




class AllocatedNode(Protocol):
    """Provider-neutral execution target materialized from a machine description."""

    name: str
    hostname: str
    role: str

    def exec(
        self,
        command: str | list[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> str: ...

    def exec_detached(
        self,
        command: str | list[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> None: ...

    def put_bytes(
        self,
        target: str,
        data: bytes,
        mode: int = 0o444,
        *,
        uid: int = 0,
        gid: int = 0,
    ) -> None: ...

    def read_bytes(self, path: str) -> bytes: ...


@dataclass(frozen=True)
class NodeGroupSpec:
    role: str
    count: int


@dataclass(frozen=True)
class DockerProviderSpec:
    image: str
    command: str | list[str] = field(default_factory=lambda: ["sleep", "infinity"])
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MachineSpec:
    path: Path
    name: str
    provider: DockerProviderSpec
    nodes: tuple[NodeGroupSpec, ...]

    @property
    def node_count(self) -> int:
        return sum(group.count for group in self.nodes)

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(group.role for group in self.nodes)


@dataclass(frozen=True)
class MachineAllocation:
    spec: MachineSpec
    nodes: tuple[AllocatedNode, ...]

    def by_role(self, role: str) -> tuple[AllocatedNode, ...]:
        return tuple(node for node in self.nodes if node.role == role)

    @property
    def hostnames(self) -> tuple[str, ...]:
        return tuple(node.hostname for node in self.nodes)


def load_machine(path: Path) -> MachineSpec:
    path = path.resolve()
    data = yaml.safe_load(path.read_text())

    if not isinstance(data, dict):
        raise ValueError(f"{path}: machine description must be a YAML mapping")
    if data.get("version") != 1:
        raise ValueError(f"{path}: only machine version 1 is supported")

    name = _required_string(data, "name", str(path))

    raw_provider = data.get("provider")
    if not isinstance(raw_provider, dict):
        raise ValueError(f"{path}: provider must be a mapping")
    provider_name = _required_string(raw_provider, "name", f"{path}: provider")
    if provider_name != "docker":
        raise ValueError(
            f"{path}: unsupported provider {provider_name!r}; only 'docker' is supported"
        )

    image = _required_string(raw_provider, "image", f"{path}: provider")
    command = raw_provider.get("command", ["sleep", "infinity"])
    if not isinstance(command, (str, list)):
        raise ValueError(f"{path}: provider.command must be a string or list")
    if isinstance(command, list) and not all(isinstance(x, str) for x in command):
        raise ValueError(f"{path}: provider.command list entries must be strings")

    environment = raw_provider.get("environment", {})
    if not isinstance(environment, dict):
        raise ValueError(f"{path}: provider.environment must be a mapping")

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError(f"{path}: nodes must be a non-empty list")

    groups: list[NodeGroupSpec] = []
    roles: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        where = f"{path}: nodes[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: node group must be a mapping")
        role = _required_string(raw, "role", where)
        if role in roles:
            raise ValueError(f"{where}: duplicate role {role!r}")
        roles.add(role)

        count = raw.get("count")
        if not isinstance(count, int) or count < 1:
            raise ValueError(f"{where}: count must be a positive integer")
        groups.append(NodeGroupSpec(role=role, count=count))

    return MachineSpec(
        path=path,
        name=name,
        provider=DockerProviderSpec(
            image=image,
            command=command,
            environment={str(k): str(v) for k, v in environment.items()},
        ),
        nodes=tuple(groups),
    )


def find_machine(start: Path, name: str) -> Path:
    """Find machines/<name>.yaml by walking from a test directory to repo root."""
    current = start.resolve()
    if current.is_file():
        current = current.parent

    for root in (current, *current.parents):
        candidate = root / "machines" / f"{name}.yaml"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"could not find machines/{name}.yaml from {start}; "
        "run pytest from inside a SeanerTest checkout or add the machine description"
    )


def _required_string(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key} must be a non-empty string")
    return value
