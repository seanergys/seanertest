# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

def test_container_runs_flux_jobs(services):
    flux = services["job-service"]

    output = flux.exec(
        [
            "flux",
            "start",
            "--test-size=1",
            "/bin/sh",
            "/opt/seanertest/input/workload.sh",
        ]
    )

    print(output)
    assert "result-one=job-one" in output
    assert "result-two=job-two" in output
    assert "result-three=job-three" in output
    assert "seanertest-one" in output
    assert "seanertest-two" in output
    assert "seanertest-three" in output
