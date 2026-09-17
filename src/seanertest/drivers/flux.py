# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import shlex
import time
from typing import Any

from seanertest.machine import AllocatedNode
from seanertest.drivers.base import ServiceDriver
from seanertest.drivers.flux_config import (
    FluxHostsSpec,
    load_flux_hosts,
    render_flux_hosts_toml,
)
from seanertest.service import Service

_FLUX_ROOT = "/tmp/seanertest/flux"
_FLUX_CONF_DIR = f"{_FLUX_ROOT}/conf.d"
_FLUX_CERT = f"{_FLUX_ROOT}/curve.cert"
_FLUX_URI = f"local://{_FLUX_ROOT}/local"
_FLUX_BROKER_LOG = f"{_FLUX_ROOT}/broker.log"


class FluxService(Service):
    def __init__(
        self,
        *,
        name: str,
        testbed: str,
        brokers: tuple[AllocatedNode, ...],
        login: AllocatedNode,
        compute: tuple[AllocatedNode, ...],
    ):
        self.name = name
        self.testbed = testbed
        self._brokers = brokers
        self._login = login
        self._compute = compute

    def exec(self, command: str | list[str]) -> str:
        """Run a command from the Flux login node inside this Flux instance."""
        if isinstance(command, str):
            command = ["/bin/sh", "-lc", command]
        return self._login.exec(command, environment={"FLUX_URI": _FLUX_URI})

    def broker_nodes(self) -> tuple[AllocatedNode, ...]:
        return self._brokers

    def compute_nodes(self) -> tuple[AllocatedNode, ...]:
        return self._compute

    def hostnames(self) -> tuple[str, ...]:
        return tuple(node.hostname for node in self._brokers)

    def login_node(self) -> AllocatedNode:
        return self._login

    def login_address(self) -> str:
        return self._login.hostname

    def flux_uri(self) -> str:
        """URI used by Flux clients inside the login-node container."""
        return _FLUX_URI

    def pyflux(self) -> Any | None:
        """Return a real pyflux handle when the pytest process can reach Flux.

        The Docker backend uses a local UNIX socket inside the login container,
        so it intentionally returns None there. A future machine provider may
        expose a host-reachable URI and return flux.Flux from this same method.
        """
        try:
            import flux  # type: ignore[import-not-found]
        except ImportError:
            return None
        if self.flux_uri().startswith("local://"):
            return None
        return flux.Flux(self.flux_uri())


class FluxDriver(ServiceDriver):
    name = "flux"

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._service: FluxService | None = None
        self._brokers: tuple[AllocatedNode, ...] = ()

    def start(self) -> FluxService:
        hosts_spec = load_flux_hosts(self.variant.hosts)
        brokers = _select_brokers(self.machine.nodes, hosts_spec)
        if not brokers:
            raise ValueError("Flux hosts description selected no broker nodes")
        self._brokers = brokers

        login_nodes = tuple(
            node for node in brokers if node.role == hosts_spec.login_role
        )
        if len(login_nodes) != 1:
            raise ValueError(
                "Flux hosts description must select exactly one login node; "
                f"role {hosts_spec.login_role!r} selected {len(login_nodes)}"
            )
        login = login_nodes[0]

        resource_by_role = {rule.role: rule for rule in hosts_spec.resources}
        unknown_resource_roles = set(resource_by_role) - {node.role for node in brokers}
        if unknown_resource_roles:
            raise ValueError(
                "Flux resource roles are not broker roles: "
                + ", ".join(sorted(unknown_resource_roles))
            )

        compute = tuple(
            node
            for node in brokers
            if (rule := resource_by_role.get(node.role)) is not None
            and rule.schedulable
        )
        if not compute:
            raise ValueError("Flux hosts description contains no schedulable nodes")

        self._prepare_nodes(brokers, hosts_spec)
        self._start_brokers(brokers)
        self._wait_ready(login, expected_size=len(brokers))

        self._service = FluxService(
            name=self.service_spec.name,
            testbed=self.testbed,
            brokers=brokers,
            login=login,
            compute=compute,
        )
        return self._service

    def stop(self) -> None:
        if self._service is None:
            return
        try:
            self._service.exec(["flux", "shutdown", "--quiet"])
        except Exception:
            pass

    def _prepare_nodes(
        self,
        brokers: tuple[AllocatedNode, ...],
        hosts_spec: FluxHostsSpec,
    ) -> None:
        leader = brokers[0]
        prepare = f"mkdir -p {_FLUX_CONF_DIR} {_FLUX_ROOT}/run {_FLUX_ROOT}/state"
        leader.exec(["/bin/sh", "-lc", prepare])
        leader.exec(["flux", "keygen", _FLUX_CERT])
        certificate = leader.read_bytes(_FLUX_CERT)

        generated = render_flux_hosts_toml(brokers, hosts_spec).encode()
        base_config = self.variant.config.read_bytes()

        for node in brokers:
            node.exec(["/bin/sh", "-lc", prepare])
            uid = int(node.exec(["id", "-u"]).strip())
            gid = int(node.exec(["id", "-g"]).strip())
            node.put_bytes(
                f"{_FLUX_CONF_DIR}/10-config.toml",
                base_config,
                uid=uid,
                gid=gid,
            )
            node.put_bytes(
                f"{_FLUX_CONF_DIR}/90-hosts.toml",
                generated,
                uid=uid,
                gid=gid,
            )
            node.put_bytes(
                _FLUX_CERT,
                certificate,
                mode=0o600,
                uid=uid,
                gid=gid,
            )

    def _start_brokers(self, brokers: tuple[AllocatedNode, ...]) -> None:
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
            node.exec_detached(["/bin/sh", "-lc", command])

    def _wait_ready(self, login: AllocatedNode, expected_size: int) -> None:
        deadline = time.monotonic() + self.backend.startup_timeout
        last_error: Exception | None = None
        root = self._brokers[0]

        while time.monotonic() < deadline:
            try:
                # `flux getattr size` is the configured broker count. It does
                # not tell us that all brokers have actually joined the
                # overlay. Readiness is therefore determined from rank 0.
                status = root.exec(
                    ["flux", "overlay", "status"],
                    environment={"FLUX_URI": _FLUX_URI},
                )
                if "full" not in status.lower():
                    time.sleep(0.2)
                    continue

                size = root.exec(
                    ["flux", "getattr", "size"],
                    environment={"FLUX_URI": _FLUX_URI},
                ).strip()

                if int(size) != expected_size:
                    last_error = RuntimeError(
                        f"Flux overlay has size {size}, expected {expected_size}"
                    )
                    time.sleep(0.2)
                    continue

                # Finally verify the user-facing broker can reach the
                # scheduler/resource services hosted upstream.
                login.exec(
                    ["flux", "resource", "list"],
                    environment={"FLUX_URI": _FLUX_URI},
                )
                return
            except Exception as exc:
                last_error = exc

            time.sleep(0.2)

        diagnostics = []
        for node in self._brokers:
            parts = [f"--- {node.hostname} ---"]

            try:
                log = node.exec(
                    [
                        "/bin/sh",
                        "-lc",
                        f"cat {_FLUX_BROKER_LOG} 2>/dev/null || true",
                    ]
                )
            except Exception as exc:
                log = f"could not read broker log: {exc}"

            if log.strip():
                parts.append(f"broker log:\n{log.rstrip()}")

            diagnostic_commands = (
                ["/bin/sh", "-lc", "ps -ef | grep '[f]lux-broker' || true"],
                ["flux", "getattr", "rank"],
                ["flux", "getattr", "size"],
                ["flux", "overlay", "status", "-v"],
                ["flux", "overlay", "errors"],
            )

            for command in diagnostic_commands:
                try:
                    if command[0] == "flux":
                        output = node.exec(
                            command,
                            environment={"FLUX_URI": _FLUX_URI},
                        )
                    else:
                        output = node.exec(command)
                    rendered = output.rstrip() or "<no output>"
                    parts.append(f"$ {' '.join(command)}\n{rendered}")
                except Exception as exc:
                    parts.append(f"$ {' '.join(command)}\nERROR: {exc}")

            diagnostics.append("\n".join(parts))

        detail = "\n".join(diagnostics)
        raise TimeoutError(
            f"Flux service did not become ready with {expected_size} brokers; "
            f"last error: {last_error}\n{detail}"
        )


def _select_brokers(
    nodes: tuple[AllocatedNode, ...], spec: FluxHostsSpec
) -> tuple[AllocatedNode, ...]:
    by_role: dict[str, list[AllocatedNode]] = {}
    for node in nodes:
        by_role.setdefault(node.role, []).append(node)

    missing = [role for role in spec.broker_roles if role not in by_role]
    if missing:
        raise ValueError(
            "machine does not provide Flux broker role(s): " + ", ".join(missing)
        )

    selected: list[AllocatedNode] = []
    for role in spec.broker_roles:
        selected.extend(by_role[role])
    return tuple(selected)
