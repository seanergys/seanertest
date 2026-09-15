from __future__ import annotations

from pathlib import Path

import pytest

from .runtime import DockerFixtureEnvironment, Services
from .spec import load_fixture


@pytest.fixture(scope="module")
def services(request: pytest.FixtureRequest) -> Services:
    """Start the services declared by fixture.yaml beside the current test file."""
    module_file = getattr(request.module, "__file__", None)
    if module_file is None:
        pytest.fail("could not determine test module path")

    test_path = Path(module_file).resolve()
    fixture_path = test_path.parent / "fixture.yaml"

    if not fixture_path.is_file():
        pytest.fail(f"missing fixture.yaml beside test: {fixture_path}")

    try:
        spec = load_fixture(fixture_path)
        environment = DockerFixtureEnvironment(spec)
        running = environment.start()

        expected = {service.name for service in spec.services}
        actual = set(running)
        if actual != expected:
            raise RuntimeError(
                f"fixture service mismatch: expected {sorted(expected)!r}, "
                f"got {sorted(actual)!r}"
            )
    except Exception as exc:
        pytest.fail(f"could not start fixture environment from {fixture_path}: {exc}")

    try:
        yield running
    finally:
        environment.stop()
