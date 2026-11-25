# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from pathlib import Path

import pytest
import seanerops

from seanertest.config import ConfigError, UpstreamCache, load_config
from seanertest.fixture import FixtureError, load_fixture

ROOT = Path(__file__).resolve().parents[2]


def test_repository_config_names_the_approved_image_and_target():
    config = load_config(ROOT / "config.yml")
    x86 = config.architecture("x86_64")
    assert x86.image.endswith("rockylinux:10")
    assert x86.target == "x86_64_v3"
    assert "gcc" in config.build_packages
    assert "gcc" not in config.install_packages
    assert config.seanerstack_pip == "seanerstack"
    assert config.upstream_caches == (
        UpstreamCache(url="oci://registry.seanergys.fz-juelich.de/software/seanerstack/buildcache", push=True),
    )


def _config_with_upstream(tmp_path, upstream: str):
    lines = (ROOT / "config.yml").read_text().splitlines()
    start = lines.index("upstream_caches:")
    end = next(index for index in range(start + 1, len(lines)) if lines[index] and not lines[index].startswith(" "))
    path = tmp_path / "config.yml"
    path.write_text("\n".join([*lines[:start], upstream, *lines[end:]]) + "\n")
    return path


def test_upstream_caches_are_urls_or_mappings_with_push(tmp_path):
    path = _config_with_upstream(
        tmp_path, "upstream_caches:\n  - oci://registry.example.org/a\n  - {url: oci://registry.example.org/b, push: true}"
    )
    assert load_config(path).upstream_caches == (
        UpstreamCache(url="oci://registry.example.org/a"),
        UpstreamCache(url="oci://registry.example.org/b", push=True),
    )


@pytest.mark.parametrize(
    ("upstream", "message"),
    [
        ("upstream_caches: oci://registry.example.org/a", "must be a list"),
        ("upstream_caches: [https://registry.example.org/a]", "oci:// URL"),
        ("upstream_caches: [{url: oci://registry.example.org/a, push: yes please}]", "true or false"),
        ("upstream_caches: [{url: oci://registry.example.org/a, write: true}]", "write"),
    ],
)
def test_invalid_upstream_caches_are_rejected(tmp_path, upstream, message):
    with pytest.raises(ConfigError, match=message):
        load_config(_config_with_upstream(tmp_path, upstream))


def test_a_spack_version_is_rejected_because_seanerstack_pins_the_commit(tmp_path):
    text = (ROOT / "config.yml").read_text()
    spack = "    git: https://github.com/spack/spack.git\n"
    assert spack in text
    path = tmp_path / "config.yml"
    path.write_text(text.replace(spack, spack + "    version: v1.2.2\n"))
    with pytest.raises(ConfigError, match="sources.spack: unknown keys: version"):
        load_config(path)


@pytest.mark.parametrize("path", sorted((ROOT / "targets").glob("*.yml")), ids=lambda path: path.stem)
def test_repository_targets_are_valid(path):
    target = seanerops.load_target(path)
    assert target.cache is not None
    load_config(ROOT / "config.yml").architecture(target.architecture)


@pytest.mark.parametrize("path", sorted(ROOT.glob("tests/*/fixture.yaml")), ids=lambda path: path.parent.name)
def test_repository_fixtures_are_valid(path):
    fixture = load_fixture(path)
    assert fixture.services


def test_fixture_with_nodes_and_services(tmp_path):
    (tmp_path / "spack.yaml").write_text("spack:\n  specs: [m4]\n")
    (tmp_path / "flux.toml").write_text("")
    (tmp_path / "fixture.yaml").write_text(
        """
version: 2
allocation: {mode: exclusive}
nodes:
  - {role: login, count: 1}
  - {role: compute, count: 2}
services:
  - name: flux
    driver: flux
    roles: [login, compute]
    software: {spack: spack.yaml}
    config: flux.toml
    options: {schedulable: [compute]}
  - name: db
    driver: container
    image: postgres:16-alpine
    ports: [5432]
"""
    )
    fixture = load_fixture(tmp_path / "fixture.yaml")
    assert fixture.request.total == 3
    assert fixture.request.mode == "exclusive"
    assert fixture.software.content == b"spack:\n  specs: [m4]\n"
    assert [service.runs_on_nodes for service in fixture.services] == [True, False]


@pytest.mark.parametrize(
    ("services", "message"),
    [
        ("  - {name: f, driver: flux, roles: [gpu], software: {spack: spack.yaml}}", "not declared in nodes"),
        ("  - {name: f, driver: slurm, roles: [node]}", "unknown driver"),
        ("  - {name: c, driver: container}", "image must be"),
        ("  - {name: c, driver: container, image: x, files: [{source: ../x, target: /x}]}", "inside the test directory"),
        (
            "  - {name: a, driver: environment, roles: [node], software: {spack: spack.yaml}}\n"
            "  - {name: b, driver: environment, roles: [node], software: {spack: other.yaml}}",
            "same spack.yaml",
        ),
    ],
)
def test_invalid_fixtures_are_rejected(tmp_path, services, message):
    (tmp_path / "spack.yaml").write_text("spack: {specs: [m4]}\n")
    (tmp_path / "other.yaml").write_text("spack: {specs: [zlib]}\n")
    (tmp_path / "fixture.yaml").write_text(f"version: 2\nnodes: [{{role: node, count: 1}}]\nservices:\n{services}\n")
    with pytest.raises(FixtureError, match=message):
        load_fixture(tmp_path / "fixture.yaml")
