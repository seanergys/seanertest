#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "tests"


def job_name(test_file: Path) -> str:
    relative = test_file.relative_to(ROOT).with_suffix("")
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(relative))
    return f"pytest:{value}"


def main() -> None:
    tests = sorted(TEST_ROOT.rglob("test_*.py"))
    if not tests:
        raise SystemExit("no test_*.py files found below tests/")

    print("stages:")
    print("  - test")
    print()
    print(".pytest-test:")
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
        print(f'"{job_name(test_file)}":')
        print("  extends: .pytest-test")
        print("  script:")
        print(f'    - pytest -v {relative}')
        print()


if __name__ == "__main__":
    main()
