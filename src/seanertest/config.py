# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""The seanertest configuration, ``config.yml``.

It holds the settings that apply to every target: where Spack and seanerstack
come from, the approved image and Spack target of each architecture, the
compiler, and the system packages installed in the Rocky Linux containers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_NAME = "config.yml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Architecture:
    name: str
    image: str
    target: str


@dataclass(frozen=True)
class SeanertestConfig:
    path: Path
    spack_git: str
    spack_version: str
    spack_packages_git: str
    seanerstack_pip: str
    compiler: str
    architectures: dict[str, Architecture]
    build_packages: tuple[str, ...]
    install_packages: tuple[str, ...]
    node_packages: tuple[str, ...]
    upstream_caches: tuple[str, ...] = ()

    def architecture(self, name: str) -> Architecture:
        try:
            return self.architectures[name]
        except KeyError as error:
            available = ", ".join(sorted(self.architectures)) or "<none>"
            raise ConfigError(
                f"{self.path}: no architecture {name!r}; available: {available}"
            ) from error


def find_config(start: Path) -> Path:
    """Find config.yml by walking upward from a directory."""
    start = start.resolve()
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(f"could not find {CONFIG_NAME} in {start} or its parents; pass --seanertest-config")


def load_config(path: Path) -> SeanertestConfig:
    path = path.resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    where = str(path)
    _mapping(data, where)
    if data.get("version") != 1:
        raise ConfigError(f"{where}: only config version 1 is supported")
    _known(data, {"version", "sources", "compiler", "architectures", "system_packages", "upstream_caches"}, where)

    sources = data.get("sources")
    _mapping(sources, f"{where}: sources")
    spack = sources.get("spack")
    _mapping(spack, f"{where}: sources.spack")
    spack_packages = sources.get("spack_packages")
    _mapping(spack_packages, f"{where}: sources.spack_packages")
    seanerstack = sources.get("seanerstack")
    _mapping(seanerstack, f"{where}: sources.seanerstack")

    architectures: dict[str, Architecture] = {}
    raw_architectures = data.get("architectures")
    _mapping(raw_architectures, f"{where}: architectures")
    for name, raw in raw_architectures.items():
        arch_where = f"{where}: architectures.{name}"
        _mapping(raw, arch_where)
        _known(raw, {"image", "target"}, arch_where)
        architectures[name] = Architecture(
            name=name, image=_string(raw, "image", arch_where), target=_string(raw, "target", arch_where)
        )

    upstream = data.get("upstream_caches", [])
    if not isinstance(upstream, list) or not all(isinstance(url, str) and url.startswith("oci://") for url in upstream):
        raise ConfigError(f"{where}: upstream_caches must be a list of oci:// URLs")

    packages = data.get("system_packages")
    _mapping(packages, f"{where}: system_packages")
    _known(packages, {"build", "install", "node"}, f"{where}: system_packages")

    return SeanertestConfig(
        path=path,
        spack_git=_string(spack, "git", f"{where}: sources.spack"),
        spack_version=_string(spack, "version", f"{where}: sources.spack"),
        spack_packages_git=_string(spack_packages, "git", f"{where}: sources.spack_packages"),
        seanerstack_pip=_string(seanerstack, "pip", f"{where}: sources.seanerstack"),
        compiler=_string(data, "compiler", where),
        architectures=architectures,
        build_packages=_packages(packages, "build", where),
        install_packages=_packages(packages, "install", where),
        node_packages=_packages(packages, "node", where),
        upstream_caches=tuple(upstream),
    )


def _packages(raw: dict, key: str, where: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ConfigError(f"{where}: system_packages.{key} must be a list of package names")
    return tuple(value)


def _mapping(value: Any, where: str) -> None:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping")


def _known(value: dict, keys: set[str], where: str) -> None:
    unknown = set(value) - keys
    if unknown:
        raise ConfigError(f"{where}: unknown keys: {', '.join(sorted(map(str, unknown)))}")


def _string(value: dict, key: str, where: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ConfigError(f"{where}: {key} must be a non-empty string")
    return item
