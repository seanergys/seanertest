# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Credentials for OCI build caches.

Environment variables take precedence. Otherwise the credentials stored by
``docker login`` are used, either from Docker's ``config.json`` or from the
credential helper it names. Nothing is written anywhere: the values go only
into the environment of the build container and into a Kubernetes Secret of
the test namespace.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path


def registry_host(url: str) -> str:
    """The registry host of an ``oci://`` URL."""
    return url.removeprefix("oci://").split("/", 1)[0]


def docker_config_path() -> Path:
    return Path(os.environ.get("DOCKER_CONFIG", Path.home() / ".docker")) / "config.json"


def from_docker(host: str) -> tuple[str, str] | None:
    """The credentials that ``docker login HOST`` stored, if any."""
    try:
        config = json.loads(docker_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    auth = config.get("auths", {}).get(host, {}).get("auth")
    if auth:
        username, _, password = base64.b64decode(auth).decode().partition(":")
        return username, password

    helper = config.get("credHelpers", {}).get(host) or config.get("credsStore")
    if not helper:
        return None
    try:
        result = subprocess.run(
            [f"docker-credential-{helper}", "get"], input=host, capture_output=True, text=True, check=True
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    return data["Username"], data["Secret"]


def oci_credentials(url: str, username_variable: str, password_variable: str) -> tuple[str, str] | None:
    """Credentials for an OCI cache: from the two variables, else from docker login."""
    username = os.environ.get(username_variable)
    password = os.environ.get(password_variable)
    if username and password:
        return username, password
    return from_docker(registry_host(url))
