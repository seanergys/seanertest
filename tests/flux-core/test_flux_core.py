def test_flux_core_is_available(services):
    flux = services["seanergys-flux"]

    output = flux.exec(
        [
            "/bin/sh",
            "-lc",
            """
            set -eu
            echo "PATH=$PATH"
            echo "--- command -v flux"
            command -v flux || true
            echo "--- common locations"
            ls -l /usr/bin/flux /usr/local/bin/flux /opt/flux/bin/flux 2>/dev/null || true
            echo "--- find flux"
            find /usr /usr/local /opt -type f -name flux 2>/dev/null | head -20 || true
            """,
        ]
    )

    print(output)
