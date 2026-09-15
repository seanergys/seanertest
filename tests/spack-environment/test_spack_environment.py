def test_spack_environment_is_available(services):
    spack = services["spack"]

    output = spack.exec(["m4", "--version"])

    assert "GNU M4" in output
