# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

def test_spack_package_is_available(services):
    environment = services["package-environment"]

    output = environment.exec(["m4", "--version"])

    print(output)
    assert "GNU M4" in output
