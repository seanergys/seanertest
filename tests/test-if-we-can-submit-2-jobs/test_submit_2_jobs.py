from seanertest import FluxService


EXPECTED = {
    "Asys": {"brokers": 11, "compute": 6, "control": 4},
    "Bsys": {"brokers": 6, "compute": 4, "control": 1},
}


def test_if_we_can_submit_2_jobs(services, testbed):
    flux = services["seanergys.flux"]
    assert isinstance(flux, FluxService)
    assert testbed in EXPECTED

    compute = flux.compute_nodes()
    assert len(compute) == EXPECTED[testbed]["compute"]

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
    assert "first-job-on-" in output
    assert "second-job-on-" in output


def test_flux_service_metadata(services, testbed):
    flux = services["seanergys.flux"]
    assert isinstance(flux, FluxService)
    assert testbed in EXPECTED

    brokers = flux.broker_nodes()
    assert len(brokers) == EXPECTED[testbed]["brokers"]
    assert sum(node.role == "control" for node in brokers) == EXPECTED[testbed]["control"]
    assert len(flux.compute_nodes()) == EXPECTED[testbed]["compute"]

    assert flux.hostnames() == tuple(node.hostname for node in brokers)
    assert flux.login_node().role == "login"
    assert flux.login_address() == flux.login_node().hostname
    assert flux.flux_uri().startswith("local://")

    print(f"testbed={testbed}")
    print(f"brokers={','.join(flux.hostnames())}")
    print(f"login={flux.login_address()}")

    # Docker keeps the local Flux connector inside the login container, so a
    # host-side pyflux handle is normally unavailable. Other providers may
    # expose a URI that allows this method to return a real flux.Flux handle.
    handle = flux.pyflux()
    if handle is not None:
        assert int(handle.attr_get("size")) == EXPECTED[testbed]["brokers"]
