# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""The build phase.

It runs before any testbed is requested. It builds every Spack environment of
the selected tests in one build container per architecture and pushes the
binaries to the target's build cache. Tests never build.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from seanertest.build.scripts import OCI_PASSWORD, OCI_USERNAME, BuildSettings, build_script
from seanertest.config import Architecture, SeanertestConfig
from seanertest.fixture import SpackEnvironment

# Environment variables that hold a token for the Git server seanerstack is
# installed from, for example CI_JOB_TOKEN in GitLab CI.
GIT_TOKEN = "SEANERTEST_GIT_TOKEN"
GIT_USERNAME = "SEANERTEST_GIT_USERNAME"


class BuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class BuiltEnvironment:
    """An environment of the build phase, keyed by everything its hashes depend on."""

    key: str
    environment: SpackEnvironment
    lock: Path


def environment_key(
    environment: SpackEnvironment,
    config: SeanertestConfig,
    architecture: Architecture,
    spack_packages_commit: str,
) -> str:
    digest = hashlib.sha256()
    for part in (
        environment.content,
        config.spack_version.encode(),
        spack_packages_commit.encode(),
        config.compiler.encode(),
        architecture.image.encode(),
        architecture.target.encode(),
    ):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()[:16]


def cache_url(cache_type: str, oci_url: str | None) -> str:
    """The build cache as the build container sees it."""
    if cache_type == "oci":
        assert oci_url is not None
        return oci_url
    return "file:///cache/buildcache"


def run_build_phase(
    environments: Iterable[SpackEnvironment],
    *,
    config: SeanertestConfig,
    architecture: Architecture,
    spack_packages_commit: str,
    cache_dir: Path,
    cache_type: str,
    oci_url: str | None = None,
    docker_client=None,
    log=print,
) -> dict[SpackEnvironment, BuiltEnvironment]:
    """Build the environments and return their lock files.

    Environments whose lock file already exists in the cache directory were
    built by an earlier session with identical inputs and are skipped.
    """
    built: dict[SpackEnvironment, BuiltEnvironment] = {}
    pending: dict[str, SpackEnvironment] = {}
    for environment in environments:
        key = environment_key(environment, config, architecture, spack_packages_commit)
        lock = cache_dir / "environments" / key / "spack.lock"
        built[environment] = BuiltEnvironment(key=key, environment=environment, lock=lock)
        if not lock.is_file():
            pending[key] = environment

    if not pending:
        log("seanertest: all environments are already built")
        return built

    log(f"seanertest: building {len(pending)} environment(s) for {architecture.name} in {architecture.image}")
    with tempfile.TemporaryDirectory(prefix="seanertest-build-") as work:
        work_dir = Path(work)
        for key, environment in pending.items():
            directory = work_dir / "environments" / key
            directory.mkdir(parents=True)
            (directory / "spack.yaml").write_bytes(environment.content)
        settings = BuildSettings(
            spack_git=config.spack_git,
            spack_version=config.spack_version,
            seanerstack_pip=config.seanerstack_pip,
            compiler=config.compiler,
            target=architecture.target,
            packages=config.build_packages,
            environments=tuple(pending),
            cache_url=cache_url(cache_type, oci_url),
            oci=cache_type == "oci",
            host_uid=os.getuid(),
            host_gid=os.getgid(),
        )
        (work_dir / "build.sh").write_text(build_script(settings), encoding="utf-8")
        _run_container(
            docker_client,
            image=architecture.image,
            work_dir=work_dir,
            cache_dir=cache_dir,
            environment=_container_environment(config.seanerstack_pip, cache_type),
            log=log,
        )

    missing = [key for key in pending if not built[pending[key]].lock.is_file()]
    if missing:
        raise BuildError(f"the build container produced no lock file for environment(s) {', '.join(missing)}")
    return built


def _container_environment(seanerstack_pip: str, cache_type: str) -> dict[str, str]:
    environment: dict[str, str] = {}
    token = os.environ.get(GIT_TOKEN)
    match = re.search(r"git\+(https://[^/]+/)", seanerstack_pip)
    if token and match:
        # Credentials for installing seanerstack from Git, passed through Git's
        # environment configuration and never written to a file.
        server = match.group(1)
        username = os.environ.get(GIT_USERNAME, "oauth2")
        authenticated = server.replace("https://", f"https://{username}:{token}@", 1)
        environment.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"url.{authenticated}.insteadOf",
                "GIT_CONFIG_VALUE_0": server,
            }
        )
    if cache_type == "oci":
        for name in (OCI_USERNAME, OCI_PASSWORD):
            if not os.environ.get(name):
                raise BuildError(f"pushing to the OCI build cache needs {name}")
            environment[name] = os.environ[name]
    return environment


def _run_container(docker_client, *, image, work_dir, cache_dir, environment, log) -> None:
    import docker

    client = docker_client or docker.from_env()
    cache_dir.mkdir(parents=True, exist_ok=True)
    container = client.containers.run(
        image,
        command=["/bin/bash", "/work/build.sh"],
        volumes={
            str(work_dir): {"bind": "/work", "mode": "rw"},
            str(cache_dir.resolve()): {"bind": "/cache", "mode": "rw"},
        },
        environment=environment,
        detach=True,
    )
    try:
        for chunk in container.logs(stream=True, follow=True):
            for line in chunk.decode(errors="replace").splitlines():
                log(f"[build] {line}")
        status = container.wait()
        if status.get("StatusCode") != 0:
            raise BuildError(f"the build container failed with exit code {status.get('StatusCode')}")
    finally:
        try:
            container.remove(force=True)
        except Exception as error:  # noqa: BLE001
            print(f"seanertest: could not remove build container: {error}", file=sys.stderr)
