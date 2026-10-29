# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""A thin wrapper around the Kubernetes client for what seanertest needs."""

from __future__ import annotations

import base64
import shlex
import time
from dataclasses import dataclass
from pathlib import Path


class ClusterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


class Cluster:
    def __init__(self, kubeconfig: Path):
        from kubernetes import client, config

        self._client = client
        self.api_client = config.new_client_from_config(config_file=str(kubeconfig))
        self.core = client.CoreV1Api(self.api_client)

    # Objects.

    def create(self, manifest: dict) -> None:
        kind = manifest["kind"]
        namespace = manifest["metadata"].get("namespace")
        if kind == "Namespace":
            self.core.create_namespace(manifest)
        elif kind == "Pod":
            self.core.create_namespaced_pod(namespace, manifest)
        elif kind == "Service":
            self.core.create_namespaced_service(namespace, manifest)
        elif kind == "ConfigMap":
            self.core.create_namespaced_config_map(namespace, manifest)
        elif kind == "Secret":
            self.core.create_namespaced_secret(namespace, manifest)
        else:
            raise ClusterError(f"unsupported kind {kind}")

    def delete_namespace(self, name: str) -> None:
        try:
            self.core.delete_namespace(name)
        except self._client.ApiException as error:
            if error.status != 404:
                raise

    # Pods.

    def pod_phase(self, namespace: str, name: str) -> str:
        return self.core.read_namespaced_pod_status(name, namespace).status.phase

    def wait_for_phase(self, namespace: str, name: str, phases: set[str], timeout: float) -> str:
        """Wait until the pod reaches one of ``phases`` or fails."""
        deadline = time.monotonic() + timeout
        while True:
            phase = self.pod_phase(namespace, name)
            if phase in phases:
                return phase
            if phase == "Failed":
                raise ClusterError(f"pod {namespace}/{name} failed\n{self.logs(namespace, name)}")
            if time.monotonic() >= deadline:
                raise ClusterError(
                    f"pod {namespace}/{name} is still {phase} after {timeout:.0f} s; "
                    "if it is Pending, the cluster may lack capacity\n" + self.describe(namespace, name)
                )
            time.sleep(1)

    def logs(self, namespace: str, name: str) -> str:
        try:
            return self.core.read_namespaced_pod_log(name, namespace)
        except self._client.ApiException as error:
            return f"<no logs: {error.reason}>"

    def describe(self, namespace: str, name: str) -> str:
        events = self.core.list_namespaced_event(namespace, field_selector=f"involvedObject.name={name}")
        return "\n".join(f"{event.reason}: {event.message}" for event in events.items)

    def exec(self, namespace: str, pod: str, argv: list[str], timeout: float | None = None) -> ExecResult:
        from kubernetes.stream import stream

        response = stream(
            self.core.connect_get_namespaced_pod_exec,
            pod,
            namespace,
            command=argv,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False,
        )
        stdout: list[str] = []
        stderr: list[str] = []
        deadline = None if timeout is None else time.monotonic() + timeout
        while response.is_open():
            response.update(timeout=1)
            if response.peek_stdout():
                stdout.append(response.read_stdout())
            if response.peek_stderr():
                stderr.append(response.read_stderr())
            if deadline is not None and time.monotonic() >= deadline:
                response.close()
                raise ClusterError(f"command {shlex.join(argv)} in {namespace}/{pod} timed out")
        response.close()
        returncode = response.returncode
        return ExecResult(returncode=0 if returncode is None else returncode, stdout="".join(stdout), stderr="".join(stderr))

    def write_file(self, namespace: str, pod: str, path: str, data: bytes, mode: int = 0o644) -> None:
        # The content travels base64-encoded in the command line, which keeps
        # binary data intact without a stdin channel.
        encoded = base64.b64encode(data).decode()
        script = 'mkdir -p "$(dirname "$2")" && printf %s "$1" | base64 -d > "$2" && chmod "$3" "$2"'
        result = self.exec(namespace, pod, ["/bin/sh", "-c", script, "seanertest", encoded, path, f"{mode:o}"])
        if result.returncode != 0:
            raise ClusterError(f"could not write {path} in {namespace}/{pod}: {result.stderr}")

    def read_file(self, namespace: str, pod: str, path: str) -> bytes:
        result = self.exec(namespace, pod, ["/bin/sh", "-c", 'base64 < "$1"', "seanertest", path])
        if result.returncode != 0:
            raise ClusterError(f"could not read {path} in {namespace}/{pod}: {result.stderr}")
        return base64.b64decode(result.stdout)

    # Nodes and services.

    def node_address(self, host: str) -> str:
        node = self.core.read_node(host)
        for address in node.status.addresses:
            if address.type == "InternalIP":
                return address.address
        raise ClusterError(f"node {host} has no InternalIP address")

    def any_node(self) -> str:
        return self.core.list_node().items[0].metadata.name

    def node_ports(self, namespace: str, service: str) -> dict[int, int]:
        spec = self.core.read_namespaced_service(service, namespace).spec
        return {port.port: port.node_port for port in spec.ports}
