from urllib.request import urlopen


def test_if_service_can_receive_config(services):
    service = services["configured-service"]

    with urlopen(f"{service.endpoint(8080)}/config.yml", timeout=5) as response:
        body = response.read().decode()

    print(body)
    assert "message: hello from configured service" in body
