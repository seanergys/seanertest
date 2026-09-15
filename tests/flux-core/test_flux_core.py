def test_flux_core_is_available(services):
    flux = services["seanergys-flux"]

    output = flux.exec(["flux", "--version"])

    assert "flux-core" in output
