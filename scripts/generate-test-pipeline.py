#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests"


def job_name(test_file: Path, testbed: str | None = None) -> str:
    relative = test_file.relative_to(ROOT).with_suffix("")
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(relative))
    if testbed is not None:
        value += "-" + re.sub(r"[^A-Za-z0-9_-]+", "-", testbed)
    return f"pytest:{value}"
def fixture_testbeds(test_file: Path) -> list[str | None]:
    fixture_path = test_file.parent / "fixture.yaml"
    if not fixture_path.is_file():
        return [None]

    data = yaml.safe_load(fixture_path.read_text())
    if not isinstance(data, dict):
        return [None]

    values: set[str] = set()
    for service in data.get("services", []):
        if not isinstance(service, dict):
            continue
        driver = service.get("driver")
        if not isinstance(driver, dict):
            continue
        config = driver.get("config")
        if not isinstance(config, dict):
            continue
        values.update(
            key
            for key in config
            if isinstance(key, str) and key.strip() and key != "generic"
        )

    return sorted(values) if values else [None]


def main() -> None:
    tests = sorted(TEST_ROOT.rglob("test_*.py"))
    if not tests:
        raise SystemExit("no test_*.py files found below tests/")

    print("stages:")
    print("  - test")
    print(".serial:")
    print("  resource_group: project-ci")
    print()
    print(".pytest-test:")
    print("  extends: .serial")
    print("  stage: test")
    print("  image: python:3.12")
    print("  tags:")
    print("    - docker")
    print("    - dind")
    print("  variables:")
    print('    DOCKER_HOST: "tcp://docker:2375"')
    print('    DOCKER_TLS_CERTDIR: ""')
    print("  before_script:")
    print("    - python -m pip install --upgrade pip")
    print("    - python -m pip install -e .")
    print()

    for test_file in tests:
        relative = test_file.relative_to(ROOT).as_posix()
        for testbed in fixture_testbeds(test_file):
            print(f'"{job_name(test_file, testbed)}":')
            print("  extends: .pytest-test")
            print("  script:")
            if testbed is None:
                # print(f"    - pytest -v --junitxml junit-${{CI_JOB_ID}}.xml -s {relative}")
                print(f"    - pytest -v --junitxml junit.xml -s {relative}")
            else:
                # print(f"    - pytest -v --junitxml junit-${{CI_JOB_ID}}.xml -s --testbed {testbed} {relative}")
                print(f"    - pytest -v --junitxml junit.xml -s --testbed {testbed} {relative}")
            print()

            print("    - python -m pip install -e .")
            print("  artifacts:")
            print("    when: always")
            print("    paths:")
            # print("      - junit-${CI_JOB_ID}.xml")
            print("      - junit.xml")


if __name__ == "__main__":
    main()
