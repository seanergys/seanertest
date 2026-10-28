# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

import errno
import socket
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from seanertest.build.phase import environment_key
from seanertest.build.scripts import STORE, BuildSettings, InstallSettings, build_script, install_script
from seanertest.build.server import CacheServer, CacheServerError
from seanertest.config import load_config
from seanertest.fixture import SpackEnvironment

ROOT = Path(__file__).resolve().parents[2]

BUILD = BuildSettings(
    spack_git="https://github.com/spack/spack.git",
    spack_version="v1.2.2",
    seanerstack_pip="seanerstack @ git+https://gitlab.example.org/seanerstack.git",
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
    assert "--branch v1.2.2" in script
    assert "toolchain bootstrap gcc@15" in script
    assert "packages:all:require:target=x86_64_v3" in script
    assert script.index("toolchain bootstrap") < script.index("environment aaaa") < script.index("environment bbbb")
    assert "cp /work/environments/aaaa/spack.yaml /work/environments/aaaa/spack.lock /cache/environments/aaaa/" in script
    assert "buildcache push --unsigned --update-index" in script
    assert "chown -R 1000:1000 /cache" in script
    assert "--oci-username-variable" not in script


def test_build_script_for_an_oci_cache_uses_credential_variables():
    script = build_script(replace(BUILD, oci=True, cache_url="oci://registry.example.org/cache"))
    assert "--oci-username-variable SEANERTEST_OCI_USERNAME --oci-password-variable SEANERTEST_OCI_PASSWORD" in script
    assert "chown" not in script


def test_install_script_installs_binaries_only_into_the_build_store():
    script = install_script(
        InstallSettings(
            spack_git="https://github.com/spack/spack.git",
            spack_version="v1.2.2",
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
