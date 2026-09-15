def test_spack_environment_is_available(services):
    spack = services["spack"]

    output = spack.exec(["hello", "--version"])

    assert "GNU Hello" in output
