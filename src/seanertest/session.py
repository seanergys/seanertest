# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""One seanertest run on one target.

The session runs the build phase, holds the testbed of the current mode group,
and starts the services of each test module in a namespace of its own.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import socket
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import seanerops
from seanerops import AllocationError, Request, Testbed
from seanerops.allocation import mode_for
from seanerstack.isolation import BUILTIN_REPO_COMMIT

from seanertest.build.phase import BuiltEnvironment, run_build_phase
from seanertest.build.scripts import OCI_PASSWORD, OCI_USERNAME, InstallSettings, activation_script, install_script
from seanertest.build.server import CacheServer
from seanertest.config import SeanertestConfig
from seanertest.drivers import get_driver
from seanertest.drivers.base import DriverContext, ServiceDriver
from seanertest.fixture import FixtureSpec, ServiceSpec, SpackEnvironment
from seanertest.kubernetes import manifests
from seanertest.kubernetes.cluster import Cluster
from seanertest.kubernetes.manifests import READY_FILE
from seanertest.kubernetes.node import PodNode
from seanertest.service import ContainerService, Service, Services

CACHE_DIR_VARIABLE = "SEANERTEST_CACHE_DIR"
CLUSTER_ONLY = "cluster"


class SessionError(RuntimeError):
    pass


def resolve_cache_dir(option: str | None, warn: Callable[[str], None]) -> tuple[Path, bool]:
    """The cache directory, and whether it is temporary."""
    value = option or os.environ.get(CACHE_DIR_VARIABLE)
    if value:
        path = Path(value).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path, False
    warn(
        "seanertest: no --cache-dir given; packages built in this run will not be reused. "
        f"Set --cache-dir or {CACHE_DIR_VARIABLE} to keep them."
    )
    return Path(tempfile.mkdtemp(prefix="seanertest-cache-")), True


def group_key(target: seanerops.Target, fixture: FixtureSpec) -> str:
    """Tests of one group share a testbed: the effective mode, or cluster-only."""
    request = fixture.request
    if request is None:
        return CLUSTER_ONLY
    return mode_for(target, request)


def group_request(target: seanerops.Target, fixtures: Iterable[FixtureSpec]) -> Request:
    """Merge the requests of a group, with the mode made explicit."""
    requests = [
        Request(groups=fixture.request.groups, mode=mode_for(target, fixture.request))
        for fixture in fixtures
        if fixture.request is not None
    ]
    return Request.merge(requests)


def kubernetes_name(value: str, limit: int = 40) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")[:limit].strip("-")
    if not name or not name[0].isalpha():
        name = f"s-{name}"
    return name


@dataclass
class _Open:
    key: str
    cluster: Cluster
    testbed: Testbed | None
    stack: contextlib.ExitStack


@dataclass
class Session:
    config: SeanertestConfig
    target: seanerops.Target
    cache_dir: Path
    cache_is_temporary: bool = False
    log: Callable[[str], None] = print
    startup_timeout: float = 600.0
    install_timeout: float = 3600.0
    fixtures: dict[Path, FixtureSpec] = field(default_factory=dict)
    built: dict[SpackEnvironment, BuiltEnvironment] = field(default_factory=dict)
    allocation_errors: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target.cache is None:
            raise SessionError(f"target {self.target.name!r} has no cache section")
        self.architecture = self.config.architecture(self.target.architecture)
        self.work_dir = Path(tempfile.mkdtemp(prefix="seanertest-work-"))
        self._server: CacheServer | None = None
        self._open: _Open | None = None

    # Build phase.

    def build(self) -> None:
        environments = {fixture.software for fixture in self.fixtures.values() if fixture.software is not None}
        if not environments:
            return
        self.built = run_build_phase(
            environments,
            config=self.config,
            architecture=self.architecture,
            spack_packages_commit=BUILTIN_REPO_COMMIT,
            cache_dir=self.cache_dir,
            cache_type=self.target.cache.type,
            oci_url=self.target.cache.url,
            log=self.log,
        )

    def _pod_cache_url(self) -> str:
        if self.target.cache.type == "oci":
            return self.target.cache.url
        if self._server is None:
            (self.cache_dir / "buildcache").mkdir(parents=True, exist_ok=True)
            self._server = CacheServer(self.cache_dir / "buildcache", self.target.cache.address).start()
        return self._server.url

    # Testbeds.

    def acquire(self, key: str) -> _Open:
        """Make the testbed of a group available, releasing the previous one."""
        if key in self.allocation_errors:
            raise AllocationError(self.allocation_errors[key])
        if self._open is not None and (self._open.key == key or key == CLUSTER_ONLY):
            return self._open
        self.release()

        stack = contextlib.ExitStack()
        work = self.work_dir / key
        try:
            if key == CLUSTER_ONLY:
                seanerops.up(self.target, None, work)
                stack.callback(seanerops.down, self.target, work)
                testbed = None
                kubeconfig = work / "output" / "kubeconfig"
            else:
                group = [fixture for fixture in self.fixtures.values() if group_key(self.target, fixture) == key]
                request = group_request(self.target, group)
                testbed = stack.enter_context(seanerops.testbed(self.target, request, work))
                kubeconfig = testbed.kubeconfig
        except AllocationError as error:
            stack.close()
            self.allocation_errors[key] = str(error)
            raise
        except BaseException:
            stack.close()
            raise
        self._open = _Open(key=key, cluster=Cluster(kubeconfig), testbed=testbed, stack=stack)
        return self._open

    def release(self) -> None:
        if self._open is not None:
            self._open.stack.close()
            self._open = None

    def close(self) -> None:
        self.release()
        if self._server is not None:
            self._server.stop()
        shutil.rmtree(self.work_dir, ignore_errors=True)
        if self.cache_is_temporary:
            shutil.rmtree(self.cache_dir, ignore_errors=True)

    # Services of one test module.

    @contextlib.contextmanager
    def services(self, fixture: FixtureSpec, module: str):
        current = self.acquire(group_key(self.target, fixture))
        cluster = current.cluster
        namespace = f"st-{kubernetes_name(module, 48)}-{secrets.token_hex(3)}"
        cluster.create(manifests.namespace(namespace))
        drivers: list[ServiceDriver] = []
        try:
            values: dict[str, Service] = {}
            nodes = self._start_nodes(cluster, namespace, fixture, current.testbed)
            address = self._service_address(cluster, current.testbed)
            for spec in fixture.services:
                if not spec.runs_on_nodes:
                    values[spec.name] = self._start_container(cluster, namespace, spec, address)
            for spec in fixture.services:
                if spec.runs_on_nodes:
                    context = DriverContext(
                        cluster=cluster,
                        namespace=namespace,
                        testbed=self.target.name,
                        nodes=nodes,
                        startup_timeout=self.startup_timeout,
                    )
                    driver = get_driver(spec.driver)(spec, context)
                    drivers.append(driver)
                    values[spec.name] = driver.start()
            yield Services(values)
        finally:
            for driver in reversed(drivers):
                driver.stop()
            cluster.delete_namespace(namespace)

    def _start_nodes(self, cluster, namespace, fixture, testbed) -> dict[str, tuple[PodNode, ...]]:
        if fixture.request is None:
            return {}
        assert testbed is not None and fixture.software is not None
        built = self.built[fixture.software]
        selected = [node for group in fixture.groups for node in testbed.by_role(group.role)[: group.count]]

        config_map = f"environment-{built.key}"
        settings = InstallSettings(
            spack_git=self.config.spack_git,
            spack_version=self.config.spack_version,
            spack_packages_git=self.config.spack_packages_git,
            spack_packages_commit=BUILTIN_REPO_COMMIT,
            packages=self.config.install_packages,
            environment=built.key,
            cache_url=self._pod_cache_url(),
            oci=self.target.cache.type == "oci",
        )
        cluster.create(
            manifests.config_map(
                namespace,
                config_map,
                {
                    "spack.yaml": built.environment.content.decode(),
                    "spack.lock": built.lock.read_text(encoding="utf-8"),
                    "install.sh": install_script(settings),
                },
            )
        )
        if settings.oci:
            cluster.create(manifests.oci_secret(namespace, os.environ[OCI_USERNAME], os.environ[OCI_PASSWORD]))

        # One installer per host, so that pods sharing a host do not install
        # the same environment at the same time.
        hosts = sorted({node.host for node in selected})
        for index, host in enumerate(hosts):
            cluster.create(
                manifests.installer_pod(
                    namespace,
                    f"install-{index}",
                    host=host,
                    image=self.architecture.image,
                    config_map_name=config_map,
                    oci=settings.oci,
                )
            )
        for index, host in enumerate(hosts):
            self.log(f"seanertest: installing environment {built.key} on {host}")
            cluster.wait_for_phase(namespace, f"install-{index}", {"Succeeded"}, self.install_timeout)

        cluster.create(manifests.nodes_service(namespace))
        for node in selected:
            cluster.create(
                manifests.node_pod(namespace, node, image=self.architecture.image, packages=self.config.node_packages)
            )
        for node in selected:
            cluster.wait_for_phase(namespace, node.name, {"Running"}, self.startup_timeout)
            self._wait_for_file(cluster, namespace, node.name, READY_FILE)

        activate = activation_script(built.key)
        nodes: dict[str, tuple[PodNode, ...]] = {}
        for group in fixture.groups:
            nodes[group.role] = tuple(
                PodNode(cluster, namespace, node, activate) for node in testbed.by_role(group.role)[: group.count]
            )
        return nodes

    def _wait_for_file(self, cluster: Cluster, namespace: str, pod: str, path: str) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while cluster.exec(namespace, pod, ["test", "-f", path]).returncode != 0:
            if time.monotonic() >= deadline:
                raise SessionError(f"pod {namespace}/{pod} did not become ready\n{cluster.logs(namespace, pod)}")
            time.sleep(1)

    def _service_address(self, cluster: Cluster, testbed: Testbed | None) -> str:
        host = testbed.nodes[0].host if testbed is not None else cluster.any_node()
        return cluster.node_address(host)

    def _start_container(self, cluster: Cluster, namespace: str, spec: ServiceSpec, address: str) -> ContainerService:
        name = kubernetes_name(spec.name)
        files: dict[str, str] = {}
        config_map = None
        if spec.files:
            config_map = f"{name}-files"
            data = {f"file-{index}": file.source.read_text(encoding="utf-8") for index, file in enumerate(spec.files)}
            files = {file.target: f"file-{index}" for index, file in enumerate(spec.files)}
            cluster.create(manifests.config_map(namespace, config_map, data))
        cluster.create(
            manifests.container_pod(
                namespace,
                name,
                image=spec.image,
                command=spec.command,
                entrypoint=spec.entrypoint,
                environment=spec.environment,
                ports=spec.ports,
                files=files,
                config_map_name=config_map,
            )
        )
        node_ports: dict[int, int] = {}
        if spec.ports:
            cluster.create(manifests.node_port_service(namespace, name, spec.ports))
            node_ports = cluster.node_ports(namespace, name)
        cluster.wait_for_phase(namespace, name, {"Running"}, self.startup_timeout)
        service = ContainerService(
            name=spec.name, cluster=cluster, namespace=namespace, pod=name, address=address, node_ports=node_ports
        )
        for command in spec.setup:
            service.exec(["/bin/sh", "-c", command])
        for port in node_ports.values():
            self._wait_for_port(address, port, spec.name)
        return service

    def _wait_for_port(self, address: str, port: int, name: str) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while True:
            try:
                with socket.create_connection((address, port), timeout=2):
                    return
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise SessionError(f"service {name!r} is not reachable at {address}:{port}") from error
                time.sleep(0.5)
