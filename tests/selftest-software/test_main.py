# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from pathlib import Path

from seanertest.spec import load_fixture


ROOT = Path(__file__).resolve().parents[2]


def test_submit_2_jobs_uses_spack_environment():
    test_root = ROOT / "tests" / "test-if-we-can-submit-2-jobs"
    fixture = load_fixture(test_root / "fixture.yaml")
    service = fixture.services[0]

    assert service.software is not None
    assert service.software.spack == test_root / "spack.yaml"


def test_complex_example_combines_driver_and_container_services():
    test_root = ROOT / "tests" / "example-complex-service-test"
    fixture = load_fixture(test_root / "fixture.yaml")

    assert [service.name for service in fixture.services] == [
        "seanergys.flux",
        "minio",
        "postgres",
    ]
    assert fixture.testbeds == ("Asys", "Bsys")

    flux = fixture.services[0]
    assert flux.software is not None
    assert flux.software.spack == test_root / "spack.yaml"
    assert fixture.services[1].ports == [9000]
    assert fixture.services[2].ports == [5432]
