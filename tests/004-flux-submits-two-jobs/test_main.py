# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from seanertest import FluxService

# The fixture asks for one control, one login and four compute nodes; the
# counts are the same on every target.
BROKERS = 6
COMPUTE = 4


def test_flux_submits_two_jobs(services):
    flux = services["seanergys.flux"]
    assert isinstance(flux, FluxService)
    assert len(flux.compute_nodes()) == COMPUTE

    output = flux.exec(
        [
            "/bin/sh",
            "-c",
            """
            set -eu
            first=$(flux submit --job-name=example-first /bin/sh -c 'echo first-job-on-$(hostname)')
            second=$(flux submit --job-name=example-second /bin/sh -c 'echo second-job-on-$(hostname)')
            echo "submitted=$first,$second"
            flux job attach "$first"
            flux job attach "$second"
            """,
        ]
    )

    print(output)
    assert "submitted=" in output
    assert "first-job-on-compute-" in output
    assert "second-job-on-compute-" in output


def test_flux_service_metadata(services, testbed):
    flux = services["seanergys.flux"]
    assert isinstance(flux, FluxService)

    brokers = flux.broker_nodes()
    assert len(brokers) == BROKERS
    assert [node.role for node in brokers] == ["control", "login"] + ["compute"] * COMPUTE
    assert flux.hostnames() == ("control-0", "login-0", "compute-0", "compute-1", "compute-2", "compute-3")
    assert flux.login_node().role == "login"
    assert flux.login_address() == "login-0"
    assert flux.flux_uri().startswith("local://")

    # Every broker carries its role and the target name as Flux properties.
    resources = flux.exec(["flux", "resource", "list", "--format", "{properties}"])
    assert "compute" in resources
    assert testbed in resources

    print(f"testbed={testbed}")
    print(f"brokers={','.join(flux.hostnames())}")
    print(f"hosts={','.join(sorted({node.host for node in brokers}))}")

    handle = flux.pyflux()
    if handle is not None:
        assert int(handle.attr_get("size")) == BROKERS
