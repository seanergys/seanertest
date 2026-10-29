<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Set up the CI runner

The integration tests run in GitLab CI on a runner with the tags `shell`, `testbed`, `generic` and
`micro`. It uses the shell executor and starts a minikube cluster for every pipeline. This guide
prepares a Rocky Linux 10 VM as that runner.

1. Run the setup script as root on the VM:

    ```bash
    sudo scripts/setup-shell-runner.sh
    ```

    It installs Docker, minikube, kubectl, uv, Git and gitlab-runner, gives the runner user access
    to Docker, and opens the build cache port 18080 to the minikube network. It can be run again to
    update the tools. `RUNNER_USER` selects the user that runs the jobs, by default `gitlab-runner`.
    The jobs never run as root.

2. Create a runner in GitLab with the tags `shell`, `testbed`, `generic` and `micro`, and register
   it with its token:

    ```bash
    sudo gitlab-runner register --non-interactive \
        --url https://gitlab.seanergys.fz-juelich.de \
        --token <token> \
        --executor shell
    ```

3. Raise the inotify limit, because minikube and the pods of several tests need more watches than
   the default of 128 instances:

    ```bash
    echo fs.inotify.max_user_instances=1024 | sudo tee /etc/sysctl.d/90-seanertest.conf
    sudo sysctl --system
    ```

4. Let the pipelines push what they build back to the seanerstack build cache. Create a deploy
   token with the scopes `read_registry` and `write_registry` in the `software` group, and store it
   as the masked CI/CD variables `SEANERTEST_UPSTREAM_USERNAME` and `SEANERTEST_UPSTREAM_PASSWORD`
   of seanertest. Without them, the jobs read the build cache with their job token and log a
   warning instead of pushing.

| Job | Runner tags | Purpose |
| --- | --- | --- |
| `test_file_names`, `lint:reuse` | `docker` | Check file names and licence headers. |
| `selftest` | `shell`, `testbed`, `generic`, `micro` | Runs the self-tests. |
| `integration:minikube` | `shell`, `testbed`, `generic`, `micro` | Starts a minikube profile, writes a target for it, and runs every numbered test. |
| `publish`, `publish:dev` | `docker` | Publish seanertest to the package index. |

The job token of seanertest's pipelines reads seanerops and seanerstack from the package index and
the compiler from the registry. Both projects must allow it in their job token allowlist.
