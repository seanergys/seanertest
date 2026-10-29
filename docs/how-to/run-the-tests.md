<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Run the tests

Seanertest is a pytest plugin, so tests are selected with the usual pytest arguments. The plugin
adds `--target`, which selects the machine, and `--cache-dir`, which keeps built software between
runs.

1. Run every integration test against a target:

    ```bash
    uv run pytest -v -s --target local --cache-dir ~/.cache/seanertest
    ```

    `local` refers to `targets/local.yml`. A path to a target file works as well.

2. Run one test directory:

    ```bash
    uv run pytest -v -s --target local --cache-dir ~/.cache/seanertest tests/003-spack-package-is-available
    ```

3. Run one test function:

    ```bash
    uv run pytest -v -s --target local --cache-dir ~/.cache/seanertest \
        "tests/004-flux-submits-two-jobs/test_main.py::test_flux_service_metadata"
    ```

Always pass the same `--cache-dir`. Without it, seanertest uses a temporary directory and builds
everything again in the next run. `SEANERTEST_TARGET` and `SEANERTEST_CACHE_DIR` set the same
values for every run.

## What happens during a run

Before the first test starts, seanertest runs the build phase. It prints the lines of the build
container with the prefix `[build]` and builds only environments that are not in the cache
directory yet. A run in which nothing changed prints
`seanertest: all environments are already built`.

| Situation | Result |
| --- | --- |
| The build phase fails. | pytest stops with exit code 3 and the message `seanertest: build phase failed`. No test runs. |
| The target cannot provide the nodes of a test, for example an exclusive test with four nodes on a single-node target. | The test is skipped, and the skip reason names the target. |
| A fixture is invalid. | pytest stops with a usage error that names the file and the setting. |
| A test runs without `--target`. | The test fails with `this test needs a target`. |

`uv run pytest --collect-only --target local` reads every fixture and reports invalid ones without
building anything.

## Troubleshooting

| Message or symptom | Cause | Remedy |
| --- | --- | --- |
| `no credentials for upstream cache` | No registry login was found. | Run `docker login registry.seanergys.fz-juelich.de` as the user that runs pytest. |
| The first run takes hours. | The compiler is built from source. | Check the registry login, then run again. |
| `[build] ERROR: No matching distribution found for seanerstack` | The build container cannot reach the package index. | Set `PIP_EXTRA_INDEX_URL`, see [Set up a workstation](set-up-a-workstation.md), or set `SEANERTEST_SEANERSTACK_SRC` to a seanerstack checkout. |
| Installer pods time out. | The pods cannot reach the cache server on the host. | Allow the cache port from the minikube network, see [Set up a workstation](set-up-a-workstation.md). |
| `cache.address ... is not an address of this host` | minikube was started again with another network. | Write the target again with `scripts/minikube-target.sh` after minikube has started. |
| `cache.port ... is already in use` | Another seanertest session runs on this host. | Wait for it to finish, or give the target another port. |
