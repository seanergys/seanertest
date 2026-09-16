from pathlib import Path

from seanertest.spec import load_fixture


ROOT = Path(__file__).resolve().parents[2]


def test_flux_service_uses_spack_environment():
    fixture = load_fixture(ROOT / "tests" / "flux-service" / "fixture.yaml")
    service = fixture.services[0]

    assert service.software is not None
    assert service.software.spack == ROOT / "tests" / "flux-service" / "env.yaml"
