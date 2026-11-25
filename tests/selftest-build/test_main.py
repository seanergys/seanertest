# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

import base64
import errno
import json
import shlex
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from seanerstack.config import load_config as load_seanerstack_config
from seanerstack.pins import BUILTIN_REPO_COMMIT, SPACK_COMMIT

from seanertest.build.phase import _container_environment, destination, environment_key, seanerstack_requirement
from seanertest.build.scripts import (
    STORE,
    BuildSettings,
    InstallSettings,
    build_script,
    install_script,
    seanerstack_config,
    upstream_resource,
)
from seanertest.build.server import CacheServer, CacheServerError
from seanertest.config import load_config
from seanertest.credentials import from_docker, oci_credentials, registry_host
from seanertest.fixture import SpackEnvironment

ROOT = Path(__file__).resolve().parents[2]

BUILD = BuildSettings(
    spack_git="https://github.com/spack/spack.git",
    spack_commit=SPACK_COMMIT,
    seanerstack_pip="seanerstack @ git+https://gitlab.example.org/seanerstack.git",
    spack_packages_commit=BUILTIN_REPO_COMMIT,
    compiler="gcc@15",
    target="x86_64_v3",
    packages=("python3", "gcc"),
    environments=("aaaa", "bbbb"),
    cache_url="file:///cache/buildcache",
    oci=False,
    host_uid=1000,
    host_gid=1000,
)


def test_build_script_bootstraps_the_compiler_builds_every_environment_and_pushes():
    script = build_script(BUILD)
    assert "dnf install -y --setopt=install_weak_deps=False python3 gcc" in script
    assert f"fetch --quiet --depth 1 https://github.com/spack/spack.git {SPACK_COMMIT}" in script
    # The compiler alone, as the toolchain of the configuration that seanerstack reads.
    assert '[toolchain]\ncompiler = "gcc@15"\npackages = []\ntarget = "x86_64_v3"\nEOF' in script
    assert "--config-file /opt/seanergys/seanerstack.toml toolchain bootstrap\n" in script
    assert "packages:all:require:target=x86_64_v3" in script
    assert script.index("[toolchain]") < script.index("toolchain bootstrap")
    assert script.index("toolchain bootstrap") < script.index("environment aaaa") < script.index("environment bbbb")
    assert (
        "cp /work/environments/aaaa/spack.yaml /work/environments/aaaa/spack.lock /cache/environments/local/aaaa/"
        in script
    )
    assert "buildcache push --unsigned --update-index" in script
    assert "trap 'chown -R 1000:1000 /cache /work' EXIT" in script
    assert script.index("trap") < script.index("dnf install")
    assert "--oci-username-variable" not in script


def test_build_script_for_an_oci_cache_uses_credential_variables():
    script = build_script(replace(BUILD, oci=True, cache_url="oci://registry.example.org/cache"))
    assert "--oci-username-variable SEANERTEST_OCI_USERNAME --oci-password-variable SEANERTEST_OCI_PASSWORD" in script


def test_build_script_reads_from_upstream_caches_before_the_compiler_bootstrap():
    script = build_script(replace(BUILD, upstream=("oci://registry.example.org/seanerstack/buildcache",)))
    # The upstream caches are seanerstack's build caches, and seanerstack makes them mirrors.
    resource = (
        "[resources.seanertest-upstream-0]\n"
        'kind = "spack-buildcache"\n'
        'url = "oci://registry.example.org/seanerstack/buildcache"\n'
        'credentials = "seanertest-upstream-0"\n'
        "signed = false\n"
    )
    assert resource in script
    assert 'target = "x86_64_v3"\ncache = "seanertest-upstream-0"\nEOF' in script
    configure = "--config-file /opt/seanergys/seanerstack.toml buildcache configure\n"
    assert script.index("activate)") < script.index(configure) < script.index("toolchain bootstrap")
    # Without push, binaries go only to the session's own cache.
    assert "push --unsigned --update-index --only package seanertest-cache" in script
    assert "push --unsigned --update-index --only package seanertest-upstream" not in script


def test_seanerstack_finds_the_compiler_lockfile_in_the_first_upstream_cache(tmp_path):
    first = "oci://registry.example.org/seanerstack/buildcache"
    path = tmp_path / "seanerstack.toml"
    path.write_text(seanerstack_config(replace(BUILD, upstream=(first, "oci://registry.example.org/other"))))
    config = load_seanerstack_config(path)
    assert config.toolchain.compiler == "gcc@15"
    assert config.toolchain.packages == ()
    assert config.toolchain.target == "x86_64_v3"
    assert config.resources[config.toolchain.cache] == upstream_resource(0, first)
    assert set(config.resources) == {"seanertest-upstream-0", "seanertest-upstream-1"}
    # The credentials of each cache, under the variables that the build phase sets.
    assert upstream_resource(1, first).credential_variables == (
        "SEANERSTACK_RESOURCE_SEANERTEST_UPSTREAM_1_USERNAME",
        "SEANERSTACK_RESOURCE_SEANERTEST_UPSTREAM_1_PASSWORD",
    )


def test_without_upstream_caches_seanerstack_has_no_build_cache(tmp_path):
    path = tmp_path / "seanerstack.toml"
    path.write_text(seanerstack_config(BUILD))
    config = load_seanerstack_config(path)
    assert config.resources == {}
    assert config.toolchain.cache not in config.resources
    assert "buildcache configure" not in build_script(BUILD)


def test_build_script_pushes_back_to_writable_upstream_caches_after_its_own_cache():
    read_only = "oci://registry.example.org/read-only"
    writable = "oci://registry.example.org/seanerstack/buildcache"
    script = build_script(replace(BUILD, upstream=(read_only, writable), push_upstream=(writable,)))
    own = script.index("push --unsigned --update-index --only package seanertest-cache ")
    upstream = script.index("push --unsigned --update-index --only package seanertest-upstream-1 ")
    assert own < upstream
    assert "--only package seanertest-upstream-0 " not in script
    # A cache that may only be read makes the push a warning.
    assert f"|| echo 'warning: could not push to the upstream cache {writable}' >&2" in script
    result = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("commit", "returncode"), [(BUILTIN_REPO_COMMIT, 0), ("0" * 40, 1)])
def test_build_script_checks_that_seanerstack_pins_the_same_commit(commit, returncode):
    line = next(line for line in build_script(BUILD).splitlines() if "BUILTIN_REPO_COMMIT" in line)
    argv = shlex.split(line)
    argv[0] = sys.executable
    argv[-1] = commit
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == returncode
    if returncode:
        assert "seanertest expects" in result.stderr


def test_locks_are_kept_per_destination_cache():
    assert destination("http", None) == "local"
    first = destination("oci", "oci://registry.example.org/a")
    assert first.startswith("oci-")
    assert first != destination("oci", "oci://registry.example.org/b")


def test_credentials_come_from_variables_before_docker_login(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    auth = base64.b64encode(b"jayesh:secret").decode()
    (tmp_path / "config.json").write_text(json.dumps({"auths": {"registry.example.org": {"auth": auth}}}))
    url = "oci://registry.example.org/group/cache"
    assert registry_host(url) == "registry.example.org"
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    assert oci_credentials(url, "A", "B") == ("jayesh", "secret")
    monkeypatch.setenv("A", "ci")
    monkeypatch.setenv("B", "token")
    assert oci_credentials(url, "A", "B") == ("ci", "token")
    assert from_docker("other.example.org") is None


def test_credentials_come_from_a_docker_credential_helper(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"auths": {"registry.example.org": {}}, "credsStore": "fake"}))
    helper = tmp_path / "docker-credential-fake"
    helper.write_text('#!/bin/sh\nread host\necho "{\\"Username\\": \\"u-$host\\", \\"Secret\\": \\"s\\"}"\n')
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    assert from_docker("registry.example.org") == ("u-registry.example.org", "s")


def test_install_script_installs_binaries_only_into_the_build_store():
    script = install_script(
        InstallSettings(
            spack_git="https://github.com/spack/spack.git",
            spack_commit=SPACK_COMMIT,
            spack_packages_git="https://github.com/spack/spack-packages.git",
            spack_packages_commit="91cfb5b973c311f742cd31061fe224d40f1fd830",
            packages=("python3",),
            environment="aaaa",
            cache_url="http://192.168.49.1:1234/token/",
            oci=False,
        )
    )
    assert f"root: {STORE}" in script
    assert "commit: 91cfb5b973c311f742cd31061fe224d40f1fd830" in script
    assert "install --use-buildcache only" in script
    assert "spack.lock" in script
    assert script.index("/.installed ]; then") < script.index("dnf install")


def test_environment_key_depends_on_everything_that_changes_hashes():
    config = load_config(ROOT / "config.yml")
    x86 = config.architecture("x86_64")
    environment = SpackEnvironment(source=Path("spack.yaml"), content=b"spack: {specs: [m4]}\n")
    key = environment_key(environment, config, x86, "commit-a")
    assert key == environment_key(environment, config, x86, "commit-a")
    assert key != environment_key(environment, config, x86, "commit-b")
    assert key != environment_key(environment, replace(config, compiler="gcc@14"), x86, "commit-a")
    assert key != environment_key(environment, config, replace(x86, target="x86_64_v4"), "commit-a")
    other = SpackEnvironment(source=Path("spack.yaml"), content=b"spack: {specs: [zlib]}\n")
    assert key != environment_key(other, config, x86, "commit-a")


def test_cache_server_serves_files_only_below_its_token(tmp_path):
    (tmp_path / "index.json").write_text("{}")
    server = CacheServer(tmp_path, "127.0.0.1").start()
    try:
        with urlopen(server.url + "index.json", timeout=5) as response:
            assert response.read() == b"{}"
        base = server.url.rsplit("/", 2)[0]
        for path in ("/index.json", f"/{server.token}/"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + path, timeout=5)
            assert error.value.code == 404
    finally:
        server.stop()


def test_cache_server_binds_a_fixed_port(tmp_path):
    (tmp_path / "index.json").write_text("{}")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = CacheServer(tmp_path, "127.0.0.1", port).start()
    try:
        assert server.url.startswith(f"http://127.0.0.1:{port}/")
        with urlopen(server.url + "index.json", timeout=5) as response:
            assert response.read() == b"{}"
        with pytest.raises(CacheServerError, match="already in use"):
            CacheServer(tmp_path, "127.0.0.1", port).start()
    finally:
        server.stop()


def test_cache_server_rejects_an_address_of_another_host(tmp_path):
    with socket.socket() as probe:
        try:
            probe.bind(("192.0.2.1", 0))
        except OSError as error:
            assert error.errno == errno.EADDRNOTAVAIL
        else:
            pytest.skip("this host owns the documentation address")
    with pytest.raises(CacheServerError, match="not an address of this host"):
        CacheServer(tmp_path, "192.0.2.1").start()


def test_compiler_only_build_bootstraps_and_pushes_without_environments():
    script = build_script(replace(BUILD, environments=()))
    assert 'compiler = "gcc@15"\npackages = []' in script
    assert "packages:all:require:target=x86_64_v3" in script
    assert script.index("packages:all:require") < script.index("toolchain bootstrap\n")
    assert "==> environment" not in script
    assert "push --unsigned --update-index --only package seanertest-cache" in script


def test_compiler_only_command_does_not_import_seanerops():
    code = "import sys, seanertest.build.__main__; sys.exit('seanerops' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_plain_seanerstack_means_the_version_installed_next_to_seanertest():
    import importlib.metadata

    installed = importlib.metadata.version("seanerstack")
    assert seanerstack_requirement("seanerstack") == f"seanerstack=={installed}"
    assert seanerstack_requirement("seanerstack @ git+https://example.org/s.git") == "seanerstack @ git+https://example.org/s.git"


def test_pip_index_settings_reach_the_build_container(monkeypatch):
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://user:token@example.org/simple")
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    monkeypatch.delenv("SEANERTEST_GIT_TOKEN", raising=False)
    environment = _container_environment("seanerstack==0.1.4.dev57", "http", None)
    assert environment == {"PIP_EXTRA_INDEX_URL": "https://user:token@example.org/simple"}
