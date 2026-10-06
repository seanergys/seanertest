# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

import time
from urllib.request import urlopen

from seanertest import FluxService


IDENTITY_COMMAND = """
host=$(cat /etc/hostname)
ip=unknown
while read -r address names; do
    case " $names " in
        *" $host "*) ip=$address; break ;;
    esac
done < /etc/hosts
printf 'hostname=%s\nip=%s\n' "$host" "$ip"
"""


def _print_identity(name, service):
    identity = service.exec(["/bin/sh", "-c", IDENTITY_COMMAND])
    print(f"--- {name} ---")
    print(identity, end="")
    assert "hostname=" in identity
    assert "ip=" in identity


def _wait_for_s3(endpoint):
    deadline = time.monotonic() + 20
    while True:
        try:
            with urlopen(endpoint, timeout=2) as response:
                return response.status
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def test_flux_s3_and_postgres_work_together(services):
    flux = services["seanergys.flux"]
    s3 = services["s3"]
    postgres = services["postgres"]

    assert isinstance(flux, FluxService)

    _print_identity("flux login", flux)
    _print_identity("s3", s3)
    _print_identity("postgres", postgres)

    flux_output = flux.exec(
        [
            "flux",
            "run",
            "-N",
            "1",
            "-n",
            "1",
            "/bin/sh",
            "-c",
            "echo flux-job-host=$(hostname)",
        ]
    )
    print("--- flux job ---")
    print(flux_output, end="")
    assert "flux-job-host=" in flux_output

    spack_output = flux.exec(
        ["spack", "find", "--format", "{name}@{version}", "flux-core", "catch2", "m4"]
    )
    print("--- installed Spack packages ---")
    print(spack_output, end="")
    assert "flux-core" in spack_output
    assert "catch2" in spack_output
    assert "m4@1.4.19" in spack_output

    s3_status = _wait_for_s3(s3.endpoint(8333))
    print(f"--- s3 ---\nhealth_status={s3_status}")
    assert s3_status == 200

    postgres_output = postgres.exec(
        [
            "psql",
            "-U",
            "seanergys",
            "-d",
            "seanergys",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atc",
            "CREATE TABLE example(value text); "
            "INSERT INTO example VALUES ('hello from postgres'); "
            "SELECT value FROM example;",
        ]
    )
    print("--- postgres query ---")
    print(postgres_output, end="")
    assert "hello from postgres" in postgres_output
