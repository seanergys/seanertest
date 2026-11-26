# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

import json

import pytest


@pytest.fixture(scope="module")
def cosched_broker_config(services):
    node = services["flux-environment"].nodes()[0]
    config_dir = node.exec(["mktemp", "-d"]).strip()
    graph_path = f"{config_dir}/scheduling.json"

    nodes = [{"id": "node0", "type": "node"}]
    edges = []
    for socket_index in range(2):
        socket = f"socket{socket_index}"
        nodes.append({"id": socket, "type": "socket"})
        edges.append({"source": "node0", "target": socket})
        for core_index in range(4):
            core = f"{socket}-core{core_index}"
            nodes.append({"id": core, "type": "core"})
            edges.append({"source": socket, "target": core})

    config = f"""\
[coscheduling-cpu]
allowed = true
resource_type = "socket"
n_way = 2
waste_threshold = 0.0

[resource]
noverify = true
scheduling = {json.dumps(graph_path)}

[[resource.config]]
hosts = {json.dumps(node.hostname)}
cores = "0-7"
"""

    try:
        graph = {"graph": {"nodes": nodes, "edges": edges}}
        node.put_bytes(graph_path, json.dumps(graph).encode())
        node.put_bytes(f"{config_dir}/flux.toml", config.encode())
        yield node, config_dir
    finally:
        node.exec(["rm", "-rf", "--", config_dir])


@pytest.mark.parametrize("subcommand", ["submit", "run"])
@pytest.mark.parametrize("no_spread", [False, True], ids=["spread", "no-spread"])
def test_cosched_jobspec(cosched_broker_config, subcommand, no_spread):
    node, config_dir = cosched_broker_config
    workload = ["hostname", "--short"]
    command = [
        "timeout", "--kill-after=5s", "45s",
        "flux", "start", "--test-size=1", f"--config-path={config_dir}",
        "flux", subcommand, "--dry-run", "-n", "4",
    ]
    if no_spread:
        command.append("--no-spread")

    jobspec = json.loads(node.exec([*command, *workload]))
    (task,) = jobspec["tasks"]
    assert task["command"] == workload

    slot = {
        "type": "slot",
        "count": 4 if no_spread else 2,
        "label": task["slot"],
        "with": [{"type": "core", "count": 1}],
    }

    if no_spread:
        assert jobspec["resources"] == [slot]
        assert task["count"] == {"per_slot": 1}
    else:
        assert jobspec["resources"] == [
            {"type": "socket", "count": 2, "with": [slot]}
        ]
        assert task["count"] == {"total": 4}

