from urllib.request import urlopen


def test_alpha_receives_config(services):
    alpha = services["alpha"]

    with urlopen(f"{alpha.endpoint(8080)}/config.yml", timeout=5) as response:
        body = response.read().decode()

    assert "message: hello from alpha" in body
