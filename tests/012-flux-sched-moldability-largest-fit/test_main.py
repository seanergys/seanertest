# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

import json
from contextlib import suppress

import pytest


@pytest.fixture(scope="module")
def fluxion(services):
    flux = services["seanergys.flux"]
    modules = flux.exec(["flux", "module", "list"])

    try:
        if "sched-simple" in modules:
            flux.exec(["flux", "module", "remove", "sched-simple"])

        if "sched-fluxion-resource" not in modules:
            flux.exec([
                "flux", "module", "load", "sched-fluxion-resource",
                "load-allowlist=node,core",
            ])

        if "sched-fluxion-qmanager" not in modules:
            flux.exec(["flux", "module", "load", "sched-fluxion-qmanager"])

        modules = flux.exec(["flux", "module", "list"])
        assert "sched-fluxion-resource" in modules, modules
        assert "sched-fluxion-qmanager" in modules, modules
    except (RuntimeError, AssertionError):
        print(flux.exec(["flux", "dmesg"]))
        raise

    return flux


@pytest.mark.parametrize(
    ("exceeds_capacity", "expected_slots", "expected_duration"),
    [
        pytest.param(False, 2, 90, id="largest-fits"),
        pytest.param(True, 1, 60, id="falls-back-to-smaller"),
    ],
)
def test_largest_fitting_cpu_shape(
    fluxion, exceeds_capacity, expected_slots, expected_duration
):
    total_cores = int(fluxion.exec([
        "flux", "resource", "list", "--states=all",
        "--no-header", "--format={ncores}",
    ]).strip())
    assert total_cores >= 2, f"Fixture needs at least two CPU cores, found {total_cores}"

    large_slots = total_cores + 1 if exceeds_capacity else 2
    jobspec = {
        "version": 1,
        "resources": [
            {
                "type": "xor_slot",
                "count": slots,
                "label": "work",
                "with": [{"type": "core", "count": 1}],
            }
            for slots in (1, large_slots)
        ],
        "attributes": {
            "system": {
                "duration": 120,
                "durations": {"work": [60, 90]},
            },
        },
        "tasks": [
            {
                "command": [
                    "/bin/sh",
                    "-c",
                    'printf "rank=%s\\n" "$FLUX_TASK_RANK"',
                ],
                "slot": "work",
                "count": {"per_slot": 1},
            },
        ],
    }

    jobid = fluxion.exec([
        "/bin/sh", "-c",
        'printf "%s\\n" "$1" | timeout 30s flux job submit -',
        "submit-jobspec", json.dumps(jobspec),
    ]).strip()

    try:
        output = fluxion.exec([
            "timeout", "--kill-after=5s", "45s",
            "flux", "job", "attach", "--read-only", jobid,
        ])
        fluxion.exec(["flux", "job", "wait-event", "-t", "15", jobid, "clean"])
    except RuntimeError:
        with suppress(RuntimeError):
            fluxion.exec(["timeout", "10s", "flux", "cancel", jobid])
        raise

    allocation = json.loads(fluxion.exec(["flux", "job", "info", jobid, "R"]))
    execution = allocation["execution"]
    assert execution["nslots"] == expected_slots
    assert execution["expiration"] - execution["starttime"] == expected_duration
    assert sorted(output.splitlines()) == [
        f"rank={rank}" for rank in range(expected_slots)
    ]

