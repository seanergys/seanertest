# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

from types import SimpleNamespace

import pytest
from seanerops import LogicalNode

from seanertest.drivers.flux import cpu_cores, flux_roles, render_flux_config
from seanertest.kubernetes import manifests

NODE = LogicalNode(
    name="compute-0",
    roles=("compute",),
    host="minikube",
    requests={"cpu": "10m", "memory": "64Mi"},
    limits={"cpu": "1", "memory": "4Gi"},
)


def test_node_pod_is_pinned_named_and_sized_from_the_testbed():
    pod = manifests.node_pod("ns", NODE, image="rockylinux:10", packages=("hostname",))
    spec = pod["spec"]
    assert spec["hostname"] == "compute-0"
    assert spec["subdomain"] == manifests.NODES_SERVICE
    assert spec["nodeSelector"] == {"kubernetes.io/hostname": "minikube"}
    container = spec["containers"][0]
    assert container["resources"] == {
        "requests": {"cpu": "10m", "memory": "64Mi"},
        "limits": {"cpu": "1", "memory": "4Gi"},
    }
    assert "dnf install" in container["command"][-1]
    assert spec["volumes"][0]["hostPath"]["path"] == manifests.HOST_DIRECTORY


def test_nodes_service_publishes_names_before_readiness():
    service = manifests.nodes_service("ns")
    assert service["spec"]["clusterIP"] == "None"
    assert service["spec"]["publishNotReadyAddresses"] is True


def test_installer_pod_reads_oci_credentials_from_the_secret():
    pod = manifests.installer_pod("ns", "install-0", host="h", image="i", config_map_name="env", oci=True)
    container = pod["spec"]["containers"][0]
    assert container["envFrom"] == [{"secretRef": {"name": manifests.OCI_SECRET}}]
    assert pod["spec"]["restartPolicy"] == "Never"


def test_container_pod_keeps_entrypoint_and_command_apart():
    pod = manifests.container_pod(
        "ns",
        "s3",
        image="seaweedfs",
        command=("mini",),
        entrypoint=None,
        environment={"A": "1"},
        ports=(8333,),
        files={"/etc/seanertest/config.yml": "file-0"},
        config_map_name="s3-files",
    )
    container = pod["spec"]["containers"][0]
    assert "command" not in container
    assert container["args"] == ["mini"]
    assert container["volumeMounts"][0]["subPath"] == "file-0"


@pytest.mark.parametrize(("quantity", "cores"), [("1", 1), ("500m", 1), ("48", 48), ("2500m", 2)])
def test_cpu_limits_become_whole_cores(quantity, cores):
    assert cpu_cores(quantity) == cores


def test_flux_roles_default_to_login_and_compute():
    assert flux_roles(("control", "login", "compute"), {}) == ("login", ("compute",))
    assert flux_roles(("node",), {}) == ("node", ("node",))
    with pytest.raises(ValueError, match="does not run on"):
        flux_roles(("login", "compute"), {"schedulable": ["gpu"]})


def test_flux_config_uses_pod_names_and_excludes_unschedulable_ranks():
    brokers = tuple(
        SimpleNamespace(hostname=name, role=role)
        for name, role in (("control-0", "control"), ("login-0", "login"), ("compute-0", "compute"))
    )
    config = render_flux_config(brokers, {"control-0": 1, "login-0": 1, "compute-0": 4}, ("compute",), "laptop")
    assert 'default_connect = "tcp://%h.nodes:%p"' in config
    assert '{ host = "compute-0" },' in config
    assert 'exclude = "0-1"' in config
    assert 'cores = "0-3"' in config
    assert 'properties = ["compute", "laptop"]' in config
