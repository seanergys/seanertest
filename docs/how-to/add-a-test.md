<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Add a test

This guide adds a new integration test to the repository. A test is one directory below `tests/`
with a `fixture.yaml`, which declares the nodes and services the test needs, and a `test_main.py`,
which checks them. CI runs every such directory on the minikube runner without further
registration.

1. Choose the directory name. It is the next free three-digit number, followed by a short statement
   of the behaviour that the test checks, in lowercase words separated by hyphens:

    ```bash
    ls tests
    mkdir tests/006-flux-runs-mpi-hello-world
    ```

    Existing numbers are never reused or changed, so that a number keeps naming the same test in
    logs and discussions. Directories that start with `selftest-` are reserved for the self-tests of
    seanertest.

2. Write `fixture.yaml`. Declare the logical nodes by role and count, and the services that run on
   them:

    ```yaml
    # SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
    #
    # SPDX-License-Identifier: MIT

    version: 2

    nodes:
      - role: login
        count: 1
      - role: compute
        count: 2

    services:
      - name: seanergys.flux
        driver: flux
        roles: [login, compute]
        software:
          spack: spack.yaml
    ```

    A fixture never names a target, a host or a node size. The guides for
    [software from Spack](use-spack-software.md), [container services](add-a-container-service.md)
    and [Flux](run-flux.md) describe the services, and the [fixture file reference](../reference/fixture-file.md)
    lists every setting.

3. Add the files that the fixture refers to, such as `spack.yaml` or a configuration file, to the
   same directory. A fixture may only refer to files inside its own directory.

4. Write `test_main.py`. Each test function asks for the `services` fixture and receives the running
   services by the names in `fixture.yaml`:

    ```python
    # SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
    #
    # SPDX-License-Identifier: MIT

    from seanertest import FluxService


    def test_job_runs_on_a_compute_node(services):
        flux = services["seanergys.flux"]
        assert isinstance(flux, FluxService)

        output = flux.exec(["flux", "run", "-N", "1", "hostname"])

        assert output.startswith("compute-")
    ```

    The services start once for the module and are shared by all of its test functions, so a test
    function must not rely on state that another one leaves behind. `exec` returns the standard
    output and raises an error with the output when the command fails. The
    [test API reference](../reference/test-api.md) describes every handle.

5. Check that the fixture is valid. Collection reads every fixture and builds nothing:

    ```bash
    uv run pytest --collect-only --target local tests/006-flux-runs-mpi-hello-world
    ```

6. Run the test against the local cluster:

    ```bash
    uv run pytest -v -s --target local --cache-dir ~/.cache/seanertest tests/006-flux-runs-mpi-hello-world
    ```

7. Run the self-tests, which check every fixture of the repository:

    ```bash
    uv run pytest tests/selftest-*
    ```

8. Commit the directory. Before committing, check the rules that CI enforces:

    | Rule | Checked by |
    | --- | --- |
    | The only Python file in the directory is `test_main.py`. | `test_file_names` |
    | Every file carries an SPDX copyright and licence header. | `lint:reuse` |
    | Every fixture is valid and declares at least one service. | `selftest` |
    | The test passes on a single-node minikube cluster, or is skipped there. | `integration:minikube` |

## Tests that need more than one host

The minikube runner has a single host. On a single-node target, logical nodes share the host by
default, so a test with several nodes still runs there. A test that requires
`allocation: {mode: exclusive}` gets one host per logical node, and it is skipped when the target
has fewer hosts than the exclusive tests of the run need together. Use the exclusive mode only when
the test depends on nodes having a host of their own, for example to measure performance, because
CI does not run it otherwise.
