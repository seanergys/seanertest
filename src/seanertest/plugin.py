# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

"""The pytest plugin.

``--target`` selects the machine. After collection, seanertest runs the build
phase for the selected tests and orders them by mode group, so that each group
gets one testbed. The ``services`` fixture starts the services of a test
module's ``fixture.yaml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import seanerops
from seanerops import AllocationError

from seanertest.build.phase import BuildError
from seanertest.build.server import CacheServerError
from seanertest.config import ConfigError, find_config, load_config
from seanertest.fixture import FIXTURE_NAME, FixtureError, load_fixture
from seanertest.service import Services
from seanertest.session import Session, SessionError, group_key, resolve_cache_dir

SESSION = pytest.StashKey[Session]()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("seanertest")
    group.addoption(
        "--target",
        default=None,
        help="Target to run on: a target file, or NAME for targets/NAME.yml (or SEANERTEST_TARGET).",
    )
    group.addoption(
        "--cache-dir",
        dest="seanertest_cache_dir",
        default=None,
        help="Directory that keeps the build cache between runs (or SEANERTEST_CACHE_DIR).",
    )
    group.addoption("--seanertest-config", default=None, help="Path to config.yml (default: found upward).")


def resolve_target(value: str, root: Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    for directory in (root.resolve(), *root.resolve().parents):
        path = directory / "targets" / f"{value}.yml"
        if path.is_file():
            return path
    raise pytest.UsageError(f"target {value!r} is neither a file nor targets/{value}.yml")


def _fixture_path(item: pytest.Item) -> Path | None:
    path = (Path(str(item.fspath)).parent / FIXTURE_NAME).resolve()
    return path if path.is_file() else None


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    import os

    value = config.getoption("--target") or os.environ.get("SEANERTEST_TARGET")
    paths = {path for item in items if (path := _fixture_path(item)) is not None}
    if not value or not paths:
        return

    try:
        seanertest_config = load_config(
            Path(config.getoption("--seanertest-config")) if config.getoption("--seanertest-config")
            else find_config(config.rootpath)
        )
        target = seanerops.load_target(resolve_target(value, config.rootpath))
        fixtures = {path: load_fixture(path) for path in sorted(paths)}
    except (ConfigError, FixtureError, seanerops.TargetError) as error:
        raise pytest.UsageError(str(error)) from error

    reporter = config.pluginmanager.get_plugin("terminalreporter")

    def log(message: str) -> None:
        if reporter is not None:
            reporter.write_line(message)
        else:
            print(message)

    cache_dir, temporary = resolve_cache_dir(config.getoption("seanertest_cache_dir"), log)
    try:
        seanertest_session = Session(
            config=seanertest_config, target=target, cache_dir=cache_dir, cache_is_temporary=temporary, log=log
        )
    except SessionError as error:
        raise pytest.UsageError(str(error)) from error
    seanertest_session.fixtures = fixtures
    config.stash[SESSION] = seanertest_session

    # Tests of one group run together, so that each group needs one testbed.
    order: dict[str, int] = {}
    for path in fixtures:
        order.setdefault(group_key(target, fixtures[path]), len(order))

    def rank(item: pytest.Item) -> int:
        path = _fixture_path(item)
        return -1 if path is None else order[group_key(target, fixtures[path])]

    items.sort(key=rank)


def pytest_collection_finish(session: pytest.Session) -> None:
    seanertest_session = session.config.stash.get(SESSION, None)
    if seanertest_session is None or session.config.option.collectonly:
        return
    try:
        seanertest_session.build()
    except BuildError as error:
        pytest.exit(f"seanertest: build phase failed: {error}", returncode=3)


def pytest_sessionfinish(session: pytest.Session) -> None:
    seanertest_session = session.config.stash.get(SESSION, None)
    if seanertest_session is not None:
        seanertest_session.close()


@pytest.fixture(scope="module")
def testbed(request: pytest.FixtureRequest) -> str | None:
    """The name of the selected target."""
    seanertest_session = request.config.stash.get(SESSION, None)
    return None if seanertest_session is None else seanertest_session.target.name


@pytest.fixture(scope="module")
def services(request: pytest.FixtureRequest) -> Services:
    """Start the services of the fixture.yaml beside the current test module."""
    module_file = Path(str(request.module.__file__))
    fixture_path = module_file.parent / FIXTURE_NAME
    if not fixture_path.is_file():
        pytest.fail(f"missing {FIXTURE_NAME} beside test: {fixture_path}")
    seanertest_session = request.config.stash.get(SESSION, None)
    if seanertest_session is None:
        pytest.fail("this test needs a target; pass --target NAME or set SEANERTEST_TARGET")

    fixture = seanertest_session.fixtures[fixture_path.resolve()]
    try:
        with seanertest_session.services(fixture, module_file.parent.name) as running:
            yield running
    except AllocationError as error:
        pytest.skip(f"target {seanertest_session.target.name!r} cannot provide this testbed: {error}")
    except (SessionError, CacheServerError) as error:
        pytest.fail(str(error))
