def test_if_we_can_submit_3_jobs(services):
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
