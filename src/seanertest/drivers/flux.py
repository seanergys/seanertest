# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Flux on the logical nodes of a testbed.

Every logical node of the service's roles runs one broker. The brokers find
each other by the logical node names, which are the host names of their pods.
Nodes of schedulable roles run jobs; the others take part in the instance
without being scheduled.
"""

from __future__ import annotations

import json
import math
import shlex
import time
from typing import Any, Protocol

from seanertest.drivers.base import ServiceDriver
from seanertest.kubernetes.manifests import NODES_SERVICE
from seanertest.service import Service

_FLUX_ROOT = "/tmp/seanertest/flux"
_FLUX_CONF_DIR = f"{_FLUX_ROOT}/conf.d"
_FLUX_CERT = f"{_FLUX_ROOT}/curve.cert"
_FLUX_URI = f"local://{_FLUX_ROOT}/local"
_FLUX_BROKER_LOG = f"{_FLUX_ROOT}/broker.log"


class FluxNode(Protocol):
    hostname: str
    role: str

    def exec(self, command: str | list[str], *, environment: dict[str, str] | None = None) -> str: ...


class FluxService(Service):
    def __init__(self, *, name: str, testbed: str, brokers: tuple, login, compute: tuple):
        self.name = name
        self.testbed = testbed
        self._brokers = brokers
        self._login = login
        self._compute = compute

    def exec(self, command: str | list[str]) -> str:
        """Run a command from the Flux login node inside this Flux instance."""
        return self._login.exec(command, environment={"FLUX_URI": _FLUX_URI})

    def broker_nodes(self) -> tuple:
        return self._brokers

    def compute_nodes(self) -> tuple:
        return self._compute

    def hostnames(self) -> tuple[str, ...]:
        return tuple(node.hostname for node in self._brokers)

    def login_node(self):
        return self._login

    def login_address(self) -> str:
        return self._login.hostname

    def flux_uri(self) -> str:
        """URI used by Flux clients inside the login node's pod."""
        return _FLUX_URI

    def pyflux(self) -> Any | None:
        """Return a real pyflux handle when the pytest process can reach Flux.

        The local connector is a UNIX socket inside the login pod, so this
        returns None unless a future setup exposes a host-reachable URI.
        """
        try:
            import flux  # type: ignore[import-not-found]
        except ImportError:
            return None
        if self.flux_uri().startswith("local://"):
            return None
        return flux.Flux(self.flux_uri())


def cpu_cores(quantity: str) -> int:
    """Whole cores for a Kubernetes CPU quantity, at least one."""
    value = float(quantity[:-1]) / 1000 if quantity.endswith("m") else float(quantity)
    return max(1, math.floor(value))


def flux_roles(roles: tuple[str, ...], options: dict) -> tuple[str, tuple[str, ...]]:
    """The login role and the schedulable roles of a Flux service."""
    login = options.get("login", "login" if "login" in roles else roles[0])
    schedulable = tuple(options.get("schedulable", ["compute"] if "compute" in roles else list(roles)))
    unknown = [role for role in (login, *schedulable) if role not in roles]
    if unknown:
        raise ValueError(f"Flux options name roles the service does not run on: {', '.join(unknown)}")
    unknown_options = set(options) - {"login", "schedulable"}
    if unknown_options:
        raise ValueError(f"unknown Flux options: {', '.join(sorted(unknown_options))}")
    return login, schedulable


def render_flux_config(brokers: tuple, cores: dict[str, int], schedulable: tuple[str, ...], testbed: str) -> str:
    """The bootstrap and resource configuration for the given brokers."""
    excluded = [rank for rank, node in enumerate(brokers) if node.role not in schedulable]
    lines = [
        "[bootstrap]",
        f"curve_cert = {json.dumps(_FLUX_CERT)}",
        "default_port = 8050",
        'default_bind = "tcp://*:%p"',
        # Pod host names resolve within the namespace when qualified with the
        # headless Service.
        f'default_connect = "tcp://%h.{NODES_SERVICE}:%p"',
        "hosts = [",
    ]
    lines.extend(f"  {{ host = {json.dumps(node.hostname)} }}," for node in brokers)
    lines.extend(["]", "", "[resource]", "noverify = true"])
    if excluded:
        lines.append(f"exclude = {json.dumps(_idset(excluded))}")
    for node in brokers:
        count = cores[node.hostname]
        lines.extend(
            [
                "",
                "[[resource.config]]",
                f"hosts = {json.dumps(node.hostname)}",
                f"cores = {json.dumps(_idset(list(range(count))))}",
                f"properties = [{json.dumps(node.role)}, {json.dumps(testbed)}]",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _idset(values: list[int]) -> str:
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


class FluxDriver(ServiceDriver):
    name = "flux"

    def start(self) -> FluxService:
        login_role, schedulable = flux_roles(self.spec.roles, self.spec.options)
        brokers = tuple(node for role in self.spec.roles for node in self.context.nodes[role])
        login = self.context.nodes[login_role][0]
        compute = tuple(node for node in brokers if node.role in schedulable)
        cores = {node.hostname: cpu_cores(node.logical.limits["cpu"]) for node in brokers}

        self._prepare(brokers, render_flux_config(brokers, cores, schedulable, self.context.testbed))
        self._start_brokers(brokers)
        self._wait_ready(brokers, login)
        self.service = FluxService(
            name=self.spec.name, testbed=self.context.testbed, brokers=brokers, login=login, compute=compute
        )
        return self.service

    def stop(self) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            try:
                service.exec(["flux", "shutdown", "--quiet"])
            except Exception:  # noqa: BLE001
                pass

    def _prepare(self, brokers: tuple, generated: str) -> None:
        prepare = f"mkdir -p {_FLUX_CONF_DIR} {_FLUX_ROOT}/run {_FLUX_ROOT}/state"
        leader = brokers[0]
        leader.exec(["/bin/sh", "-c", prepare])
        leader.exec(["flux", "keygen", _FLUX_CERT])
        certificate = leader.read_bytes(_FLUX_CERT)
        base = self.spec.config.read_bytes() if self.spec.config is not None else b""
        for node in brokers:
            node.exec(["/bin/sh", "-c", prepare])
            node.put_bytes(f"{_FLUX_CONF_DIR}/10-config.toml", base)
            node.put_bytes(f"{_FLUX_CONF_DIR}/90-hosts.toml", generated.encode())
            node.put_bytes(_FLUX_CERT, certificate, mode=0o600)

    def _start_brokers(self, brokers: tuple) -> None:
        for node in brokers:
            command = (
                f"exec flux broker --config-path={shlex.quote(_FLUX_CONF_DIR)} "
                "--setattr=broker.boot-method=config "
                "--setattr=broker.rc2_none=1 "
                f"--setattr=local-uri={shlex.quote(_FLUX_URI)} "
                f"--setattr=rundir={shlex.quote(_FLUX_ROOT + '/run')} "
                f"--setattr=statedir={shlex.quote(_FLUX_ROOT + '/state')} "
                f">{shlex.quote(_FLUX_BROKER_LOG)} 2>&1"
            )
            node.exec_detached(command)

    def _wait_ready(self, brokers: tuple, login) -> None:
        deadline = time.monotonic() + self.context.startup_timeout
        environment = {"FLUX_URI": _FLUX_URI}
        root = brokers[0]
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                # The configured size alone does not show that every broker
                # has joined, so readiness is judged from rank 0's overlay.
                if "full" not in root.exec(["flux", "overlay", "status"], environment=environment).lower():
                    time.sleep(0.5)
                    continue
                size = int(root.exec(["flux", "getattr", "size"], environment=environment).strip())
                if size != len(brokers):
                    last_error = RuntimeError(f"Flux overlay has size {size}, expected {len(brokers)}")
                    time.sleep(0.5)
                    continue
                login.exec(["flux", "resource", "list"], environment=environment)
                return
            except Exception as error:  # noqa: BLE001
                last_error = error
            time.sleep(0.5)

        diagnostics = []
        for node in brokers:
            try:
                log = node.exec(["/bin/sh", "-c", f"cat {_FLUX_BROKER_LOG} 2>/dev/null || true"])
            except Exception as error:  # noqa: BLE001
                log = f"could not read broker log: {error}"
            diagnostics.append(f"--- {node.hostname} ---\n{log.rstrip()}")
        raise TimeoutError(
            f"Flux did not become ready with {len(brokers)} brokers; last error: {last_error}\n" + "\n".join(diagnostics)
        )
