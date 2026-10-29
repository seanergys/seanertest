# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from urllib.request import urlopen


def test_service_receives_config(services):
    service = services["configured-service"]

    with urlopen(f"{service.endpoint(8080)}/config.yml", timeout=5) as response:
        body = response.read().decode()

    print(body)
    assert "message: hello from configured service" in body
