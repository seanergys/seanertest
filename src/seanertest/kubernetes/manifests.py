# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Kubernetes manifests, as plain dictionaries.

Every function here is pure, so the shape of what seanertest creates in a
cluster can be tested without one.
"""

from __future__ import annotations

from seanerops import LogicalNode

from seanertest.build.scripts import OCI_PASSWORD, OCI_USERNAME, PREFIX

MANAGED_BY = {"app.kubernetes.io/managed-by": "seanertest"}

# The headless Service that gives logical nodes resolvable host names, as
# <name>.<NODES_SERVICE> within the namespace.
NODES_SERVICE = "nodes"
NODE_LABEL = "seanertest/node"

# Directory on each cluster host shared by the pods of that host. It holds
# Spack, the installed environments and their store, and survives sessions.
HOST_DIRECTORY = "/var/lib/seanertest"

READY_FILE = "/tmp/seanertest-ready"
OCI_SECRET = "seanertest-oci"

# Kubernetes injects <SERVICE>_PORT=tcp://... and similar variables for every
# Service of the namespace. Images read such names as their own settings, for
# example SeaweedFS takes S3_PORT as its port, so they are switched off. Pods
# find services through DNS.
SERVICE_LINKS = {"enableServiceLinks": False}


def namespace(name: str) -> dict:
    return {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name, "labels": dict(MANAGED_BY)}}


def nodes_service(namespace: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": NODES_SERVICE, "namespace": namespace, "labels": dict(MANAGED_BY)},
        "spec": {
            "clusterIP": "None",
            "selector": {NODE_LABEL: "true"},
            # Brokers have to resolve each other while they start.
            "publishNotReadyAddresses": True,
        },
    }


def config_map(namespace: str, name: str, data: dict[str, str]) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": name, "namespace": namespace, "labels": dict(MANAGED_BY)},
        "data": dict(data),
    }


def oci_secret(namespace: str, username: str, password: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": OCI_SECRET, "namespace": namespace, "labels": dict(MANAGED_BY)},
        "type": "Opaque",
        "stringData": {OCI_USERNAME: username, OCI_PASSWORD: password},
    }


def _host_volume() -> dict:
    return {"name": "seanertest", "hostPath": {"path": HOST_DIRECTORY, "type": "DirectoryOrCreate"}}


def installer_pod(
    namespace: str,
    name: str,
    *,
    host: str,
    image: str,
    config_map_name: str,
    oci: bool,
) -> dict:
    """A pod that installs one environment on one host from the build cache."""
    container: dict = {
        "name": "install",
        "image": image,
        "command": ["/bin/bash", "/seanertest/install.sh"],
        "volumeMounts": [
            {"name": "seanertest", "mountPath": PREFIX},
            {"name": "environment", "mountPath": "/seanertest", "readOnly": True},
        ],
    }
    if oci:
        container["envFrom"] = [{"secretRef": {"name": OCI_SECRET}}]
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace, "labels": dict(MANAGED_BY)},
        "spec": {
            **SERVICE_LINKS,
            "restartPolicy": "Never",
            "nodeSelector": {"kubernetes.io/hostname": host},
            "containers": [container],
            "volumes": [
                _host_volume(),
                {"name": "environment", "configMap": {"name": config_map_name}},
            ],
        },
    }


def node_pod(namespace: str, node: LogicalNode, *, image: str, packages: tuple[str, ...]) -> dict:
    """The pod of one logical node. Services are started in it later."""
    install = ""
    if packages:
        install = f"dnf install -y --setopt=install_weak_deps=False {' '.join(packages)} && "
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": node.name,
            "namespace": namespace,
            "labels": {**MANAGED_BY, NODE_LABEL: "true", "seanertest/role": node.role},
        },
        "spec": {
            **SERVICE_LINKS,
            "hostname": node.name,
            "subdomain": NODES_SERVICE,
            "restartPolicy": "Never",
            "nodeSelector": {"kubernetes.io/hostname": node.host},
            "containers": [
                {
                    "name": "node",
                    "image": image,
                    "command": ["/bin/bash", "-c", f"{install}touch {READY_FILE} && exec sleep infinity"],
                    "resources": {"requests": dict(node.requests), "limits": dict(node.limits)},
                    "volumeMounts": [{"name": "seanertest", "mountPath": PREFIX, "readOnly": True}],
                }
            ],
            "volumes": [_host_volume()],
        },
    }


def container_pod(
    namespace: str,
    name: str,
    *,
    image: str,
    command: tuple[str, ...] | None,
    entrypoint: tuple[str, ...] | None,
    environment: dict[str, str],
    ports: tuple[int, ...],
    files: dict[str, str],
    config_map_name: str | None,
) -> dict:
    """The pod of a container service, which keeps its own image.

    ``files`` maps target paths to keys of the config map holding them.
    """
    container: dict = {
        "name": "service",
        "image": image,
        "env": [{"name": key, "value": value} for key, value in environment.items()],
        "ports": [{"containerPort": port} for port in ports],
    }
    # Kubernetes' command replaces the image's entrypoint and args its command.
    if entrypoint is not None:
        container["command"] = list(entrypoint)
    if command is not None:
        container["args"] = list(command)
    pod: dict = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {**MANAGED_BY, "seanertest/service": name},
        },
        "spec": {**SERVICE_LINKS, "restartPolicy": "Never", "containers": [container]},
    }
    if files and config_map_name is not None:
        container["volumeMounts"] = [
            {"name": "files", "mountPath": target, "subPath": key, "readOnly": True} for target, key in files.items()
        ]
        pod["spec"]["volumes"] = [{"name": "files", "configMap": {"name": config_map_name}}]
    return pod


def node_port_service(namespace: str, name: str, ports: tuple[int, ...]) -> dict:
    """Expose a container service's ports on the cluster hosts."""
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace, "labels": dict(MANAGED_BY)},
        "spec": {
            "type": "NodePort",
            "selector": {"seanertest/service": name},
            "ports": [{"name": f"tcp-{port}", "port": port, "targetPort": port} for port in ports],
        },
    }
