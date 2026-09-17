def test_if_spack_package_is_available(services):
    environment = services["package-environment"]

    output = environment.exec(["m4", "--version"])

    print(output)
    assert "GNU M4" in output
