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
import importlib.metadata
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from seanerstack.pins import SPACK_COMMIT

from seanertest.build.scripts import (
    OCI_PASSWORD,
    OCI_USERNAME,
    UPSTREAM_PASSWORD,
    UPSTREAM_USERNAME,
    BuildSettings,
    build_script,
)
from seanertest.config import Architecture, SeanertestConfig, UpstreamCache
from seanertest.credentials import oci_credentials

if TYPE_CHECKING:
    # Only for annotations: the fixture parser imports seanerops, which a
    # compiler-only build does not need.
    from seanertest.fixture import SpackEnvironment

# Environment variables that hold a token for the Git server seanerstack is
# installed from, for example CI_JOB_TOKEN in GitLab CI.
GIT_TOKEN = "SEANERTEST_GIT_TOKEN"
GIT_USERNAME = "SEANERTEST_GIT_USERNAME"

# pip's index settings, passed into the build container, so that it installs
# seanerstack from the same package index as the host.
PIP_INDEX_VARIABLES = ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL")


def seanerstack_requirement(pip: str) -> str:
    """The pip requirement for seanerstack in the build container.

    A plain ``seanerstack`` means the version installed next to seanertest.
    Both then pin the same spack-packages commit, which the pods clone.
    """
    if pip.strip() == "seanerstack":
        return f"seanerstack=={importlib.metadata.version('seanerstack')}"
    return pip


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
        SPACK_COMMIT.encode(),
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


def destination(cache_type: str, oci_url: str | None) -> str:
    """Names the cache that binaries are pushed to.

    Lock files are kept per destination: a lock file proves that its binaries
    are in that cache, not in another one.
    """
    if cache_type == "oci":
        assert oci_url is not None
        return "oci-" + hashlib.sha256(oci_url.encode()).hexdigest()[:12]
    return "local"


def run_build_phase(
    environments: Iterable[SpackEnvironment],
    *,
    config: SeanertestConfig,
    architecture: Architecture,
    spack_packages_commit: str,
    cache_dir: Path,
    cache_type: str,
    oci_url: str | None = None,
    upstream: tuple[UpstreamCache, ...] = (),
    seanerstack_src: Path | None = None,
    docker_client=None,
    log=print,
) -> dict[SpackEnvironment, BuiltEnvironment]:
    """Build the environments and return their lock files.

    Environments whose lock file already exists in the cache directory were
    built by an earlier session with identical inputs and are skipped.
    """
    built: dict[SpackEnvironment, BuiltEnvironment] = {}
    pending: dict[str, SpackEnvironment] = {}
    target = destination(cache_type, oci_url)
    for environment in environments:
        key = environment_key(environment, config, architecture, spack_packages_commit)
        lock = cache_dir / "environments" / target / key / "spack.lock"
        built[environment] = BuiltEnvironment(key=key, environment=environment, lock=lock)
        if not lock.is_file():
            pending[key] = environment

    if not pending:
        log("seanertest: all environments are already built")
        return built

    log(f"seanertest: building {len(pending)} environment(s) for {architecture.name} in {architecture.image}")
    _run_build(
        {key: environment.content for key, environment in pending.items()},
        config=config,
        architecture=architecture,
        spack_packages_commit=spack_packages_commit,
        cache_dir=cache_dir,
        cache_type=cache_type,
        oci_url=oci_url,
        upstream=upstream,
        seanerstack_src=seanerstack_src,
        docker_client=docker_client,
        log=log,
    )

    missing = [key for key in pending if not built[pending[key]].lock.is_file()]
    if missing:
        raise BuildError(f"the build container produced no lock file for environment(s) {', '.join(missing)}")
    return built


def build_compiler(
    *,
    config: SeanertestConfig,
    architecture: Architecture,
    spack_packages_commit: str,
    cache_dir: Path,
    cache_type: str,
    oci_url: str | None = None,
    upstream: tuple[UpstreamCache, ...] = (),
    seanerstack_src: Path | None = None,
    docker_client=None,
    log=print,
) -> None:
    """Bootstrap only the compiler and push it, with everything it needs.

    This is the build script of a session without environments, so the
    compiler gets the same hash as in every session: building it takes hours,
    and later sessions install it from the cache instead.
    """
    log(f"seanertest: building {config.compiler} for {architecture.name} in {architecture.image}")
    _run_build(
        {},
        config=config,
        architecture=architecture,
        spack_packages_commit=spack_packages_commit,
        cache_dir=cache_dir,
        cache_type=cache_type,
        oci_url=oci_url,
        upstream=upstream,
        seanerstack_src=seanerstack_src,
        docker_client=docker_client,
        log=log,
    )


def _run_build(
    environments: dict[str, bytes],
    *,
    config: SeanertestConfig,
    architecture: Architecture,
    spack_packages_commit: str,
    cache_dir: Path,
    cache_type: str,
    oci_url: str | None,
    upstream: tuple[UpstreamCache, ...],
    seanerstack_src: Path | None,
    docker_client,
    log,
) -> None:
    """Run the build script in a build container for the given spack.yaml contents."""
    target = destination(cache_type, oci_url)
    environment_variables = _container_environment(config.seanerstack_pip, cache_type, oci_url)
    upstream_caches = []
    for cache in upstream:
        if cache.url == oci_url:
            continue
        credentials = oci_credentials(cache.url, UPSTREAM_USERNAME, UPSTREAM_PASSWORD)
        if credentials is None:
            log(
                f"seanertest: no credentials for upstream cache {cache.url}; everything it holds is built from "
                f"source. Run docker login or set {UPSTREAM_USERNAME} and {UPSTREAM_PASSWORD}"
            )
            continue
        environment_variables[UPSTREAM_USERNAME], environment_variables[UPSTREAM_PASSWORD] = credentials
        upstream_caches.append(cache)
    # The build script returns its files to the calling user; should that ever
    # fail, a leftover directory must not abort the session.
    with tempfile.TemporaryDirectory(prefix="seanertest-build-", ignore_cleanup_errors=True) as work:
        work_dir = Path(work)
        for key, content in environments.items():
            directory = work_dir / "environments" / key
            directory.mkdir(parents=True)
            (directory / "spack.yaml").write_bytes(content)
        settings = BuildSettings(
            spack_git=config.spack_git,
            spack_commit=SPACK_COMMIT,
            seanerstack_pip=(
                "/src/seanerstack" if seanerstack_src is not None else seanerstack_requirement(config.seanerstack_pip)
            ),
            spack_packages_commit=spack_packages_commit,
            compiler=config.compiler,
            target=architecture.target,
            packages=config.build_packages,
            environments=tuple(environments),
            cache_url=cache_url(cache_type, oci_url),
            oci=cache_type == "oci",
            host_uid=os.getuid(),
            host_gid=os.getgid(),
            locks=f"/cache/environments/{target}",
            upstream=tuple(cache.url for cache in upstream_caches),
            push_upstream=tuple(cache.url for cache in upstream_caches if cache.push),
        )
        (work_dir / "build.sh").write_text(build_script(settings), encoding="utf-8")
        _run_container(
            docker_client,
            image=architecture.image,
            work_dir=work_dir,
            cache_dir=cache_dir,
            environment=environment_variables,
            seanerstack_src=seanerstack_src,
            log=log,
        )


def _container_environment(seanerstack_pip: str, cache_type: str, oci_url: str | None) -> dict[str, str]:
    environment: dict[str, str] = {name: os.environ[name] for name in PIP_INDEX_VARIABLES if os.environ.get(name)}
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
        assert oci_url is not None
        credentials = oci_credentials(oci_url, OCI_USERNAME, OCI_PASSWORD)
        if credentials is None:
            raise BuildError(
                f"no credentials for {oci_url}; run docker login or set {OCI_USERNAME} and {OCI_PASSWORD}"
            )
        environment[OCI_USERNAME], environment[OCI_PASSWORD] = credentials
    return environment


def _run_container(docker_client, *, image, work_dir, cache_dir, environment, seanerstack_src, log) -> None:
    import docker

    client = docker_client or docker.from_env()
    cache_dir.mkdir(parents=True, exist_ok=True)
    volumes = {
        str(work_dir): {"bind": "/work", "mode": "rw"},
        str(cache_dir.resolve()): {"bind": "/cache", "mode": "rw"},
    }
    if seanerstack_src is not None:
        volumes[str(Path(seanerstack_src).resolve())] = {"bind": "/src/seanerstack", "mode": "ro"}
    container = client.containers.run(
        image,
        command=["/bin/bash", "/work/build.sh"],
        volumes=volumes,
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
