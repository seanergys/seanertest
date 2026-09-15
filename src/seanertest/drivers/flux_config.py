from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

_FLUX_ROOT = "/tmp/seanertest/flux"
_FLUX_CERT = f"{_FLUX_ROOT}/curve.cert"


class FluxNodeLike(Protocol):
    hostname: str
    role: str


@dataclass(frozen=True)
class FluxResourceRule:
    role: str
    cores: str
    gpus: str | None
    properties: tuple[str, ...]
    schedulable: bool


@dataclass(frozen=True)
class FluxHostsSpec:
    broker_roles: tuple[str, ...]
    login_role: str
    resources: tuple[FluxResourceRule, ...]


def load_flux_hosts(path: Path) -> FluxHostsSpec:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: Flux hosts file must be a YAML mapping")
    if data.get("version") != 1:
        raise ValueError(f"{path}: only Flux hosts version 1 is supported")

    raw_brokers = data.get("brokers")
    if not isinstance(raw_brokers, dict):
        raise ValueError(f"{path}: brokers must be a mapping")
    raw_roles = raw_brokers.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles or not all(
        isinstance(role, str) and role.strip() for role in raw_roles
    ):
        raise ValueError(f"{path}: brokers.roles must be a non-empty string list")

    raw_login = data.get("login")
    if not isinstance(raw_login, dict):
        raise ValueError(f"{path}: login must be a mapping")
    login_role = raw_login.get("role")
    if not isinstance(login_role, str) or not login_role.strip():
        raise ValueError(f"{path}: login.role must be a non-empty string")

    raw_resources = data.get("resources")
    if not isinstance(raw_resources, list) or not raw_resources:
        raise ValueError(f"{path}: resources must be a non-empty list")

    resources: list[FluxResourceRule] = []
    seen_roles: set[str] = set()
    for index, raw in enumerate(raw_resources):
        where = f"{path}: resources[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: resource rule must be a mapping")
        role = raw.get("role")
        cores = raw.get("cores")
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"{where}: role must be a non-empty string")
        if role in seen_roles:
            raise ValueError(f"{where}: duplicate resource role {role!r}")
        seen_roles.add(role)
        if not isinstance(cores, str) or not cores.strip():
            raise ValueError(f"{where}: cores must be a non-empty Flux idset string")

        gpus = raw.get("gpus")
        if gpus is not None and (not isinstance(gpus, str) or not gpus.strip()):
            raise ValueError(f"{where}: gpus must be a non-empty Flux idset string")

        raw_properties = raw.get("properties", [role])
        if not isinstance(raw_properties, list) or not all(
            isinstance(value, str) and value.strip() for value in raw_properties
        ):
            raise ValueError(f"{where}: properties must be a string list")

        schedulable = raw.get("schedulable", True)
        if not isinstance(schedulable, bool):
            raise ValueError(f"{where}: schedulable must be boolean")

        resources.append(
            FluxResourceRule(
                role=role,
                cores=cores,
                gpus=gpus,
                properties=tuple(raw_properties),
                schedulable=schedulable,
            )
        )

    if login_role not in raw_roles:
        raise ValueError(f"{path}: login role {login_role!r} is not a broker role")

    return FluxHostsSpec(
        broker_roles=tuple(raw_roles),
        login_role=login_role,
        resources=tuple(resources),
    )


def render_flux_hosts_toml(
    brokers: tuple[FluxNodeLike, ...],
    spec: FluxHostsSpec,
) -> str:
    resource_by_role = {rule.role: rule for rule in spec.resources}
    missing = {node.role for node in brokers} - set(resource_by_role)
    if missing:
        raise ValueError(
            "Flux hosts file has no resource rule for broker role(s): "
            + ", ".join(sorted(missing))
        )

    excluded_ranks = [
        rank
        for rank, node in enumerate(brokers)
        if not resource_by_role[node.role].schedulable
    ]

    lines = [
        "[bootstrap]",
        f'curve_cert = {json.dumps(_FLUX_CERT)}',
        "default_port = 8050",
        'default_bind = "tcp://*:%p"',
        'default_connect = "tcp://%h:%p"',
        "hosts = [",
    ]
    lines.extend(f"  {{ host = {json.dumps(node.hostname)} }}," for node in brokers)
    lines.extend(["]", "", "[resource]", "verify = false"])
    if excluded_ranks:
        lines.append(f'exclude = {json.dumps(_format_idset(excluded_ranks))}')

    for node in brokers:
        rule = resource_by_role[node.role]
        lines.extend(
            [
                "",
                "[[resource.config]]",
                f"hosts = {json.dumps(node.hostname)}",
                f"cores = {json.dumps(rule.cores)}",
            ]
        )
        if rule.gpus is not None:
            lines.append(f"gpus = {json.dumps(rule.gpus)}")
        if rule.properties:
            props = ", ".join(json.dumps(value) for value in rule.properties)
            lines.append(f"properties = [{props}]")

    lines.append("")
    return "\n".join(lines)


def _format_idset(values: list[int]) -> str:
    if not values:
        return ""
    values = sorted(set(values))
    parts: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)
