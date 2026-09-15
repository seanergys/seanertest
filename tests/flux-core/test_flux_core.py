def test_flux_core_is_available(services):
    flux = services["flux-core"]
    # flux cluster with 8 nodes
    # config.yaml with coschedculding

    output = flux.exec(["flux", "--version"])

    assert "flux-core" in output
