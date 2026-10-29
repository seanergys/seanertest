# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Logical nodes as pods, the execution targets of node services."""

from __future__ import annotations

import shlex

from seanerops import LogicalNode

from seanertest.kubernetes.cluster import Cluster


class PodNode:
    """One logical node, represented by a pod whose host name is the node's name."""

    def __init__(self, cluster: Cluster, namespace: str, logical: LogicalNode, activate: str | None):
        self.cluster = cluster
        self.namespace = namespace
        self.logical = logical
        self.activate = activate

    @property
    def name(self) -> str:
        return self.logical.name

    @property
    def hostname(self) -> str:
        return self.logical.name

    @property
    def role(self) -> str:
        return self.logical.role

    @property
    def host(self) -> str:
        return self.logical.host

    def __repr__(self) -> str:
        return f"PodNode({self.name!r}, role={self.role!r}, host={self.host!r})"

    def _prelude(self, environment: dict[str, str] | None) -> str:
        parts = []
        if self.activate is not None:
            parts.append(f". {shlex.quote(self.activate)}")
        for key, value in (environment or {}).items():
            parts.append(f"export {key}={shlex.quote(value)}")
        return "".join(f"{part}\n" for part in parts)

    def _argv(self, command: str | list[str], environment: dict[str, str] | None, detached: bool = False) -> list[str]:
        prelude = self._prelude(environment)
        if isinstance(command, str):
            body = command if not detached else f"setsid nohup /bin/bash -c {shlex.quote(command)} >/dev/null 2>&1 </dev/null &"
            return ["/bin/bash", "-c", prelude + body]
        run = 'setsid nohup "$@" >/dev/null 2>&1 </dev/null &' if detached else 'exec "$@"'
        return ["/bin/bash", "-c", prelude + run, "seanertest", *command]

    def exec(self, command: str | list[str], *, environment: dict[str, str] | None = None) -> str:
        result = self.cluster.exec(self.namespace, self.name, self._argv(command, environment))
        if result.returncode != 0:
            raise RuntimeError(
                f"command {command!r} failed on node {self.name!r} with exit code {result.returncode}\n"
                f"{result.stdout}{result.stderr}"
            )
        return result.stdout

    def exec_detached(self, command: str | list[str], *, environment: dict[str, str] | None = None) -> None:
        result = self.cluster.exec(self.namespace, self.name, self._argv(command, environment, detached=True))
        if result.returncode != 0:
            raise RuntimeError(f"could not start {command!r} on node {self.name!r}: {result.stderr}")

    def put_bytes(self, target: str, data: bytes, mode: int = 0o444, *, uid: int = 0, gid: int = 0) -> None:
        self.cluster.write_file(self.namespace, self.name, target, data, mode)

    def read_bytes(self, path: str) -> bytes:
        return self.cluster.read_file(self.namespace, self.name, path)
