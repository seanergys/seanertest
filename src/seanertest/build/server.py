# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""Serving the build cache of a single-node target over HTTP.

The server runs in a thread of the pytest process and stops with it. It binds
to the host's address on the cluster's network, so that the pods can reach it
but other machines cannot, and it serves the cache read-only below a random
path segment that changes with every session.
"""

from __future__ import annotations

import errno
import functools
import secrets
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class CacheServerError(RuntimeError):
    pass


class _Handler(SimpleHTTPRequestHandler):
    token = ""

    def _strip_token(self) -> bool:
        prefix = f"/{self.token}/"
        if not self.path.startswith(prefix):
            self.send_error(404)
            return False
        self.path = "/" + self.path[len(prefix) :]
        return True

    def do_GET(self) -> None:  # noqa: N802
        if self._strip_token():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._strip_token():
            super().do_HEAD()

    def list_directory(self, path):  # noqa: ANN001
        self.send_error(404)
        return None

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass


class CacheServer:
    def __init__(self, directory: Path, address: str):
        self.directory = directory
        self.address = address
        self.token = secrets.token_urlsafe(24)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise CacheServerError("cache server is not running")
        return f"http://{self.address}:{self._server.server_address[1]}/{self.token}/"

    def start(self) -> CacheServer:
        handler = type("CacheHandler", (_Handler,), {"token": self.token})
        factory = functools.partial(handler, directory=str(self.directory))
        try:
            self._server = ThreadingHTTPServer((self.address, 0), factory)
        except OSError as error:
            if error.errno == errno.EADDRNOTAVAIL:
                raise CacheServerError(
                    f"cache.address {self.address} is not an address of this host; for minikube's "
                    "Docker driver it is the gateway shown by `docker network inspect <profile>`"
                ) from error
            raise
        self._thread = threading.Thread(target=self._server.serve_forever, name="seanertest-cache", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
