from pathlib import Path
import tomllib
from types import SimpleNamespace

from seanertest.drivers.flux_config import load_flux_hosts, render_flux_hosts_toml
from seanertest.machine import load_machine
from seanertest.spec import load_fixture


ROOT = Path(__file__).resolve().parents[2]


def test_machine_descriptions_have_expected_topology():
    asys = load_machine(ROOT / "machines" / "Asys.yaml")
    bsys = load_machine(ROOT / "machines" / "Bsys.yaml")

    assert [(g.role, g.count) for g in asys.nodes] == [
        ("control", 4),
        ("login", 1),
        ("compute", 6),
    ]
    assert [(g.role, g.count) for g in bsys.nodes] == [
        ("control", 1),
        ("login", 1),
        ("compute", 4),
    ]


def test_flux_fixture_selects_testbed_specific_config():
    fixture = load_fixture(
        ROOT / "tests" / "test-if-we-can-submit-2-jobs" / "fixture.yaml"
    )
    driver = fixture.services[0].driver
    assert driver is not None

    assert driver.select("Asys").hosts.name == "hosts.yaml"
    assert driver.select("Asys").hosts.parent.name == "Asys"
    assert driver.select("Bsys").config.parent.name == "Bsys"
    assert driver.select("unknown").config.parent.name == "generic"


def test_flux_host_template_concretizes_real_hostnames():
    hosts = load_flux_hosts(
        ROOT
        / "tests"
        / "test-if-we-can-submit-2-jobs"
        / "configs"
        / "Bsys"
        / "hosts.yaml"
    )
    nodes = tuple(
        SimpleNamespace(hostname=hostname, role=role)
        for hostname, role in [
            ("bsys-control-0", "control"),
            ("bsys-login-0", "login"),
            ("bsys-compute-0", "compute"),
            ("bsys-compute-1", "compute"),
            ("bsys-compute-2", "compute"),
            ("bsys-compute-3", "compute"),
        ]
    )

    rendered = render_flux_hosts_toml(nodes, hosts)  # type: ignore[arg-type]

    assert 'host = "bsys-login-0"' in rendered
    assert 'hosts = "bsys-compute-3"' in rendered
    assert 'properties = ["compute", "bsys"]' in rendered
    assert 'exclude = "0-1"' in rendered
    assert "noverify = true" in rendered

    parsed = tomllib.loads(rendered)
    assert len(parsed["bootstrap"]["hosts"]) == 6
    assert parsed["resource"]["exclude"] == "0-1"
    assert parsed["resource"]["noverify"] is True
    assert len(parsed["resource"]["config"]) == 6
