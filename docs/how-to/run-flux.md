<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Run Flux on the logical nodes

The `flux` driver starts one Flux broker on every logical node of the roles it names, and the
brokers form one Flux instance. The brokers find each other by the logical node names, which are
the host names of their pods. This guide adds a Flux instance to a test.

1. Add `flux-core` to the test's `spack.yaml`:

    ```yaml
    spack:
      specs:
        - flux-core@0.78.0
      concretizer:
        unify: true
      view: true
    ```

2. Declare the nodes and the Flux service in `fixture.yaml`:

    ```yaml
    nodes:
      - role: login
        count: 1
      - role: compute
        count: 4

    services:
      - name: seanergys.flux
        driver: flux
        roles: [login, compute]
        software:
          spack: spack.yaml
        config: flux.toml
    ```

    The first role in `roles` holds rank 0. The nodes are named after their role and an index, here
    `login-0` and `compute-0` to `compute-3`.

3. Choose the login node and the nodes that run jobs, if the defaults do not fit. By default, the
   login node is the first node of the role `login`, and the nodes of the role `compute` run jobs.
   When no role is called `compute`, every node runs jobs:

    ```yaml
        options:
          login: login
          schedulable: [compute]
    ```

    Nodes of other roles take part in the instance without being scheduled.

4. Write `flux.toml` with any further Flux configuration, or leave out `config`. Seanertest
   generates the `[bootstrap]` and `[resource]` tables from the testbed, so the file must not
   contain them:

    ```toml
    [tbon]
    tcp_user_timeout = "10s"
    ```

5. Submit jobs from the test. `exec` runs a command on the login node with `FLUX_URI` set to the
   instance:

    ```python
    from seanertest import FluxService


    def test_job_runs_on_a_compute_node(services):
        flux = services["seanergys.flux"]
        assert isinstance(flux, FluxService)

        output = flux.exec(["flux", "run", "-N", "1", "hostname"])

        assert output.startswith("compute-")
    ```

Every broker has two Flux properties: its role and the name of the target. A job can therefore be
sent to the nodes of a role with a constraint such as `flux run --requires=compute`. Each node
offers as many cores as its CPU limit, at least one.
