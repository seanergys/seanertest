# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Seanerstack's Spack recipes, packed for the installer pods.

Spack needs the recipe of every package it installs, also from a build cache.
The build container finds the recipes of seanerstack's namespace in the
seanerstack it installs, which is the version next to seanertest, so the pods
get the same recipes from here.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile
from pathlib import Path

import seanerstack.paths

# Directory of the recipes inside the archive. Spack imports a repository's
# recipes as Python modules below spack_repo.<namespace>.
ARCHIVE_ROOT = "spack_repo/seanerstack"


def recipes() -> Path:
    """The recipe repository of the seanerstack installed next to seanertest."""
    return seanerstack.paths.repository_path()


def archive(path: Path) -> bytes:
    """A gzipped tar of a recipe repository below ARCHIVE_ROOT.

    The same files always give the same bytes, so a digest of the archive
    names its content.
    """
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for source in sorted(path.rglob("*")):
                relative = source.relative_to(path)
                if "__pycache__" in relative.parts or source.suffix == ".pyc":
                    continue
                info = tar.gettarinfo(str(source), f"{ARCHIVE_ROOT}/{relative.as_posix()}")
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o755 if source.is_dir() else 0o644
                if source.is_file():
                    with source.open("rb") as content:
                        tar.addfile(info, content)
                else:
                    tar.addfile(info)
    return buffer.getvalue()


def digest(data: bytes) -> str:
    """A short name for the content of an archive."""
    return hashlib.sha256(data).hexdigest()[:16]
