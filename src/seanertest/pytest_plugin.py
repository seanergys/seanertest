from __future__ import annotations

import os
from pathlib import Path

import pytest

from .machine import find_machine, load_machine
from .runtime import FixtureEnvironment
from .service import Services
from .spec import load_fixture


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("seanertest")
    group.addoption(
        "--testbed",
        action="store",
        default=None,
        help=(
            "Seanertest machine/testbed name. Loads machines/<name>.yaml and "
            "selects the matching driver.config entry (falling back to generic)."
        ),
    )


@pytest.fixture(scope="module")
def testbed(request: pytest.FixtureRequest) -> str | None:
    """The selected SeanerTest testbed name, if this fixture needs one."""
    value = request.config.getoption("--testbed") or os.environ.get(
        "SEANERTEST_TESTBED"
    )
    return value or None


@pytest.fixture(scope="module")
def services(request: pytest.FixtureRequest, testbed: str | None) -> Services:
    """Start fixture.yaml beside the current test module."""
    module_file = getattr(request.module, "__file__", None)
    if module_file is None:
        pytest.fail("could not determine test module path")

    test_path = Path(module_file).resolve()
    fixture_path = test_path.parent / "fixture.yaml"
    if not fixture_path.is_file():
        pytest.fail(f"missing fixture.yaml beside test: {fixture_path}")

    environment: FixtureEnvironment | None = None
    try:
        spec = load_fixture(fixture_path)
        machine_spec = None
        if spec.requires_machine:
            if testbed is None:
                available = ", ".join(spec.testbeds) or "<none>"
                pytest.fail(
                    "this fixture requires a machine testbed; pass "
                    f"--testbed NAME (fixture-specific testbeds: {available})"
                )
            machine_path = find_machine(test_path.parent, testbed)
            machine_spec = load_machine(machine_path)

        environment = FixtureEnvironment(
            spec,
            machine_spec=machine_spec,
            testbed=testbed,
        )
        running = environment.start()
    except Exception as exc:
        if environment is not None:
            environment.stop()
        pytest.fail(f"could not start fixture environment from {fixture_path}: {exc}")

    try:
        yield running
    finally:
        environment.stop()
