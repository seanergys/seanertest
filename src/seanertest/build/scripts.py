# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Shell scripts run inside the approved Rocky Linux image.

The build script runs once per architecture in a build container. It installs
every environment of the selected tests into one Spack instance and pushes the
binaries to the build cache. The install script runs in one installer pod per
host. It installs an environment from the build cache, never from source.

Both use the same install root, so binaries need no relocation between the
build container and the pods.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass

from seanerstack.config import Resource

# Root of everything seanertest puts into containers. On cluster hosts it is a
# hostPath directory shared by the pods of that host.
PREFIX = "/opt/seanergys"

# Seanerstack state directory in the build container. Its store is the install
# root, which the pods use as well. It is seanerstack's default state
# directory, where the binaries of the seanerstack build cache were built:
# Spack cannot relocate a binary into a longer path, and the path of the
# compiler is part of the hash of everything built with it.
STATE_DIR = f"{PREFIX}/state"
STORE = f"{STATE_DIR}/spack/store"

# What seanerstack's toolchain bootstrap installs in the build container.
SEANERSTACK_CONFIG = f"{PREFIX}/seanerstack.toml"

# Name of the build cache in Spack's mirror configuration.
MIRROR = "seanertest-cache"
UPSTREAM_MIRROR = "seanertest-upstream"

# Credentials for an OCI build cache, read by Spack from these variables.
OCI_USERNAME = "SEANERTEST_OCI_USERNAME"
OCI_PASSWORD = "SEANERTEST_OCI_PASSWORD"

# Key of seanerstack's recipe repository in the installer's ConfigMap: a
# gzipped tar, base64-encoded, because a ConfigMap holds text.
RECIPES_ARCHIVE = "seanerstack-recipes.tar.gz.base64"

# Credentials for the upstream caches on the host. The build container gets
# them under the variables of each cache's seanerstack resource.
UPSTREAM_USERNAME = "SEANERTEST_UPSTREAM_USERNAME"
UPSTREAM_PASSWORD = "SEANERTEST_UPSTREAM_PASSWORD"


@dataclass(frozen=True)
class BuildSettings:
    spack_git: str
    spack_commit: str
    seanerstack_pip: str
    spack_packages_commit: str
    compiler: str
    target: str
    packages: tuple[str, ...]
    environments: tuple[str, ...]
    cache_url: str
    oci: bool
    host_uid: int
    host_gid: int
    locks: str = "/cache/environments/local"
    upstream: tuple[str, ...] = ()
    push_upstream: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstallSettings:
    spack_git: str
    spack_commit: str
    spack_packages_git: str
    spack_packages_commit: str
    packages: tuple[str, ...]
    environment: str
    cache_url: str
    oci: bool
    # Digest of the archive of seanerstack's recipes, which names the directory
    # the pods unpack it into. Without it, only Spack's own recipes are there.
    seanerstack_recipes: str | None = None


def spack_root(commit: str) -> str:
    return f"{PREFIX}/spack-{commit[:12]}"


def upstream_resource(index: int, url: str) -> Resource:
    """Upstream cache `index` of the build container as a seanerstack build cache.

    Its name is also the name of its Spack mirror, and its credentials are
    read from the variables of `Resource.credential_variables`.
    """
    name = f"{UPSTREAM_MIRROR}-{index}"
    return Resource(name=name, kind="spack-buildcache", url=url, credentials=name, signed=False)


def seanerstack_config(settings: BuildSettings) -> str:
    """The seanerstack configuration of the build container.

    The toolchain is the compiler alone, without the packages of seanerstack's
    own toolchain, such as rust, which no test needs. The upstream caches are
    its build caches, and the first one holds the lockfile of the compiler, as
    the seanerstack build cache does: the bootstrap then installs the compiler
    that the cache holds instead of building it.
    """
    resources = [upstream_resource(index, url) for index, url in enumerate(settings.upstream)]
    # TOML strings are JSON strings.
    lines = []
    for resource in resources:
        lines += [
            f"[resources.{resource.name}]",
            f"kind = {json.dumps(resource.kind)}",
            f"url = {json.dumps(resource.url)}",
            f"credentials = {json.dumps(resource.credentials)}",
            "signed = false",
            "",
        ]
    lines += [
        "[toolchain]",
        f"compiler = {json.dumps(settings.compiler)}",
        "packages = []",
        f"target = {json.dumps(settings.target)}",
    ]
    if resources:
        lines.append(f"cache = {json.dumps(resources[0].name)}")
    return "\n".join(lines) + "\n"


def environment_dir(environment: str) -> str:
    return f"{PREFIX}/environments/{environment}"


def activation_script(environment: str) -> str:
    return f"{environment_dir(environment)}/activate.sh"


def _mirror_add(
    url: str,
    oci: bool,
    name: str = MIRROR,
    username: str = OCI_USERNAME,
    password: str = OCI_PASSWORD,
) -> str:
    credentials = ""
    if oci:
        credentials = f" --oci-username-variable {username} --oci-password-variable {password}"
    return (
        f"spack mirror remove --scope user {name} >/dev/null 2>&1 || true\n"
        f"spack mirror add --scope user --type binary --unsigned{credentials} {name} {shlex.quote(url)}\n"
    )


def _dnf(packages: tuple[str, ...]) -> str:
    if not packages:
        return ""
    return f"dnf install -y --setopt=install_weak_deps=False {' '.join(map(shlex.quote, packages))}\n"


def _clone_spack(git: str, commit: str) -> str:
    # A commit is not a branch or tag, which `git clone --branch` needs, so the
    # repository is fetched at that one commit, as seanerstack does.
    root = spack_root(commit)
    return (
        f"if [ ! -x {root}/bin/spack ]; then\n"
        f"  rm -rf {root}.partial\n"
        f"  git init --quiet {root}.partial\n"
        f"  git -C {root}.partial fetch --quiet --depth 1 {shlex.quote(git)} {shlex.quote(commit)}\n"
        f"  git -C {root}.partial -c advice.detachedHead=false checkout --quiet FETCH_HEAD\n"
        f"  mv {root}.partial {root}\n"
        "fi\n"
    )


def build_script(settings: BuildSettings) -> str:
    """The script of the build container.

    The cache directory of the host is mounted at /cache and the session's
    environments at /work/environments/<id>/spack.yaml.
    """
    root = spack_root(settings.spack_commit)
    seanerstack = (
        f"seanerstack --state-dir {STATE_DIR} --spack-executable {root}/bin/spack --config-file {SEANERSTACK_CONFIG}"
    )
    lines = [
        "set -euo pipefail",
        "# The container runs as root. Return everything it wrote on the host to the",
        "# calling user, also when the build fails halfway.",
        f"trap 'chown -R {settings.host_uid}:{settings.host_gid} /cache /work' EXIT",
        "",
        "# The image lacks most tools that Spack needs, and the compiler bootstrap",
        "# needs the system compiler.",
        _dnf(settings.packages).rstrip(),
        _clone_spack(settings.spack_git, settings.spack_commit).rstrip(),
        "python3 -m venv /opt/seanerstack",
        f"/opt/seanerstack/bin/pip install --quiet {shlex.quote(settings.seanerstack_pip)}",
        "export PATH=/opt/seanerstack/bin:$PATH",
        "",
        "# The pods clone the spack-packages commit that seanertest's seanerstack pins.",
        "# Binaries match only if this seanerstack pins the same one.",
        "/opt/seanerstack/bin/python -c 'import sys; from seanerstack.pins import BUILTIN_REPO_COMMIT as c; "
        f"sys.exit(0 if c == sys.argv[1] else f\"seanerstack pins spack-packages {{c}}, seanertest expects {{sys.argv[1]}}\")' "
        f"{settings.spack_packages_commit}",
        "",
        "# seanerstack's bootstrap installs the toolchain of its configuration.",
        f"mkdir -p {PREFIX}",
        f"cat > {SEANERSTACK_CONFIG} <<'EOF'\n{seanerstack_config(settings)}EOF",
        "",
        "# Downloaded sources survive in the host's cache directory.",
        f"mkdir -p {STATE_DIR}/spack /cache/source-cache /cache/environments",
        f"ln -sfn /cache/source-cache {STATE_DIR}/spack/source-cache",
        f'eval "$({seanerstack} activate)"',
        _mirror_add(settings.cache_url, settings.oci).rstrip(),
        *(
            ["# seanerstack makes its build caches, the upstream caches, mirrors.", f"{seanerstack} buildcache configure"]
            if settings.upstream
            else []
        ),
        f"spack config add {shlex.quote(f'packages:all:require:target={settings.target}')}",
        "",
        "# The bootstrapped compiler comes from a build cache when one has it.",
        f"{seanerstack} toolchain bootstrap",
        "",
    ]
    for environment in settings.environments:
        work = f"/work/environments/{environment}"
        lines += [
            f"echo '==> environment {environment}'",
            f"spack -e {work} concretize --force",
            f'spack -e {work} install --jobs "$(nproc)"',
            f"mkdir -p {settings.locks}/{environment}",
            f"cp {work}/spack.yaml {work}/spack.lock {settings.locks}/{environment}/",
            "",
        ]
    every_spec = "$(spack find --format '/{hash}')"
    lines += [
        "# Push everything, the compiler and what came from upstream caches included,",
        "# so that the next build and the pods install binaries instead of building.",
        f"spack buildcache push --unsigned --update-index --only package {MIRROR} {every_spec}",
    ]
    for index, url in enumerate(settings.upstream):
        if url not in settings.push_upstream:
            continue
        lines += [
            "",
            f"# Return what was built here to {url}. Spack skips the binaries that it",
            "# has already. Credentials that may only read make this a warning, not a",
            "# failed build.",
            f"spack buildcache push --unsigned --update-index --only package {UPSTREAM_MIRROR}-{index} {every_spec} \\",
            f"  || echo {shlex.quote(f'warning: could not push to the upstream cache {url}')} >&2",
        ]
    return "\n".join(line for line in lines if line is not None) + "\n"


def install_script(settings: InstallSettings) -> str:
    """The script of an installer pod.

    The environment's spack.yaml and spack.lock are mounted at /seanertest.
    PREFIX is a hostPath directory, so the result is shared by every pod on
    the host and reused by later sessions.
    """
    root = spack_root(settings.spack_commit)
    target = environment_dir(settings.environment)
    commit = settings.spack_packages_commit
    unpack: list[str] = []
    seanerstack_repo = ""
    if settings.seanerstack_recipes is not None:
        # Hosts keep it for later sessions; the digest in the name keeps the
        # recipes of different seanerstack versions apart.
        recipes = f"{PREFIX}/package_repos/seanerstack-{settings.seanerstack_recipes}"
        seanerstack_repo = f"  seanerstack: {recipes}/spack_repo/seanerstack\n"
        unpack = [
            "# Spack needs the recipe of every package it installs, also from a build cache.",
            f"if [ ! -d {recipes} ]; then",
            f"  partial=$(mktemp -d {PREFIX}/package_repos/.seanerstack-XXXXXX)",
            f'  base64 -d /seanertest/{RECIPES_ARCHIVE} | tar -xz -C "$partial"',
            '  chmod 755 "$partial"',
            "  # Another installer may have unpacked the same recipes meanwhile.",
            f'  mv -T "$partial" {recipes} 2>/dev/null || rm -rf "$partial"',
            "fi",
        ]
    repos = (
        "repos::\n"
        f"{seanerstack_repo}"
        "  builtin:\n"
        f"    git: {settings.spack_packages_git}\n"
        f"    commit: {commit}\n"
        f"    destination: {PREFIX}/package_repos/builtin-{commit[:12]}\n"
    )
    config = (
        "config:\n"
        f"  install_tree:\n    root: {STORE}\n"
        f"  build_stage:\n  - {PREFIX}/stage\n"
        f"  misc_cache: {PREFIX}/cache/misc\n"
    )
    return "\n".join(
        [
            "set -euo pipefail",
            f"if [ -f {target}/.installed ]; then echo 'environment already installed'; exit 0; fi",
            _dnf(settings.packages).rstrip(),
            _clone_spack(settings.spack_git, settings.spack_commit).rstrip(),
            f"export PATH={root}/bin:$PATH",
            f"export SPACK_USER_CONFIG_PATH={PREFIX}/user SPACK_USER_CACHE_PATH={PREFIX}/cache",
            "unset SPACK_DISABLE_LOCAL_CONFIG",
            f"mkdir -p {PREFIX}/user {PREFIX}/package_repos {target}",
            *unpack,
            f"cat > {PREFIX}/user/config.yaml <<'EOF'\n{config}EOF",
            f"cat > {PREFIX}/user/repos.yaml <<'EOF'\n{repos}EOF",
            _mirror_add(settings.cache_url, settings.oci).rstrip(),
            f"cp /seanertest/spack.yaml /seanertest/spack.lock {target}/",
            f"spack -e {target} install --use-buildcache only",
            f"spack env activate --sh -d {target} > {target}/activate.sh",
            f"touch {target}/.installed",
            "",
        ]
    )
