<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Give a test software from Spack

Software on the logical nodes of a test comes from a Spack environment. Seanertest builds it once
in the build phase, before any test runs, and the pods install the ready-built binaries from the
build cache. This guide adds an environment to a test.

1. Write a `spack.yaml` in the test directory. Pin every version that the test depends on, and
   keep the view, so that the packages are on `PATH` on the nodes:

    ```yaml
    # SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
    #
    # SPDX-License-Identifier: MIT

    spack:
      specs:
        - flux-core@0.78.0
        - m4@1.4.19
      concretizer:
        unify: true
      view: true
    ```

    The recipes come from the `spack-packages` commit that seanerstack pins. The compiler, `gcc@15`,
    and the Spack target, `x86_64_v3`, are set by `config.yml` and are not part of the environment.
    A version can also be a Git commit, such as `catch2@ab6c7375be9a8e71ee84c6f8537113f9f47daf99`.

2. Refer to the environment from a node service in `fixture.yaml`. The `environment` driver
   installs the packages on the nodes without starting a service:

    ```yaml
    nodes:
      - role: node
        count: 1

    services:
      - name: tools
        driver: environment
        roles: [node]
        software:
          spack: spack.yaml
    ```

    All node services of a fixture share the logical nodes and must therefore name the same
    `spack.yaml`.

3. Use the packages in the test. Every command on a node runs with the environment activated, and
   `SPACK_ENV` names its directory:

    ```python
    def test_m4_is_installed(services):
        output = services["tools"].exec(["m4", "--version"])

        assert "(GNU M4) 1.4.19" in output
    ```

4. Build the environment on its own to check that it concretizes and builds, without starting a
   cluster:

    ```bash
    uv run python -m seanertest.build --cache-dir ~/.cache/seanertest tests/006-flux-runs-mpi-hello-world/fixture.yaml
    ```

    The next test run with the same `--cache-dir` installs the environment without building it.

Seanertest identifies an environment by the content of its `spack.yaml` and by the build settings in
`config.yml`. Any change to the file, including a comment, builds the environment again.
