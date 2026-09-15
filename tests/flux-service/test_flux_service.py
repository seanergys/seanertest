from seanertest import FluxService


EXPECTED = {
    "Asys": {"brokers": 11, "compute": 6, "control": 4},
    "Bsys": {"brokers": 6, "compute": 4, "control": 1},
}


def test_hello_world_from_every_compute_node(services, testbed):
    flux = services["seanergys.flux"]
    assert isinstance(flux, FluxService)
    assert testbed in EXPECTED

    compute = flux.compute_nodes()
    expected_hosts = {node.hostname for node in compute}
    assert len(compute) == EXPECTED[testbed]["compute"]

    output = flux.exec(
        [
            "flux",
            "run",
            "-N",
            str(len(compute)),
            "-n",
            str(len(compute)),
            "/bin/sh",
            "-c",
            'echo "hello from $(hostname)"',
        ]
    )

    seen_hosts = {
        line.removeprefix("hello from ").strip()
        for line in output.splitlines()
        if line.startswith("hello from ")
    }
    assert seen_hosts == expected_hosts


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

    # Docker keeps the local Flux connector inside the login container, so a
    # host-side pyflux handle is normally unavailable. Other providers may
    # expose a URI that allows this method to return a real flux.Flux handle.
    handle = flux.pyflux()
    if handle is not None:
        assert int(handle.attr_get("size")) == EXPECTED[testbed]["brokers"]
