<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Set up a workstation

This guide prepares a Linux x86_64 machine to run seanertest against a local minikube cluster. The
result is a checkout whose self-tests pass and a target file for the cluster.

The machine needs Docker, which the current user may use without `sudo`, as well as Git, uv,
minikube and kubectl. It needs access to GitHub and to the SEANERGYS GitLab.

1. Clone seanertest:

    ```bash
    git clone https://gitlab.seanergys.fz-juelich.de/software/seanertest.git
    cd seanertest
    ```

2. Create a GitLab personal access token with the `read_api` scope. Seanertest depends on seanerops
   and seanerstack, which are published to the package index of the SEANERGYS GitLab group, and that
   index needs authentication even for reading.

3. Add the package index to `~/.config/uv/uv.toml`:

    ```toml
    [[index]]
    name = "seanergys"
    url = "https://gitlab.seanergys.fz-juelich.de/api/v4/groups/software/-/packages/pypi/simple"
    ```

    The index is configured in uv and not in the repository, so that moving the packages to another
    index changes no file in seanertest.

4. Provide the token to uv and to pip, for example in the shell profile:

    ```bash
    export UV_INDEX_SEANERGYS_USERNAME=<token-name>
    export UV_INDEX_SEANERGYS_PASSWORD=<token>
    export PIP_EXTRA_INDEX_URL="https://<token-name>:<token>@gitlab.seanergys.fz-juelich.de/api/v4/groups/software/-/packages/pypi/simple"
    ```

    uv installs seanertest's dependencies. The build container installs seanerstack with pip, and
    seanertest passes `PIP_EXTRA_INDEX_URL` into it.

5. Log in to the SEANERGYS registry, without a port:

    ```bash
    docker login registry.seanergys.fz-juelich.de
    ```

    The build container then installs the compiler from the seanerstack build cache instead of
    building it for hours. Docker stores logins by the exact host name, so a login for
    `registry.seanergys.fz-juelich.de:443` is not used.

6. Install the dependencies and run the self-tests, which need no cluster:

    ```bash
    uv sync
    uv run pytest tests/selftest-*
    ```

7. Start minikube with the Docker driver:

    ```bash
    minikube start
    ```

8. Write a target for the cluster. The script finds the address of the host on minikube's network
   and gives the cache server the fixed port 18080:

    ```bash
    scripts/minikube-target.sh minikube ~/.kube/config 18080 > targets/local.yml
    ```

9. If the host runs a firewall that drops inbound traffic, as ufw does by default, allow the cache
   port from the minikube network:

    ```bash
    sudo ufw allow in from 192.168.49.0/24 to 192.168.49.1 port 18080 proto tcp
    ```

    The pods install their software over HTTP from a cache server that seanertest runs on the host.
    Without this rule, the installer pods wait until they time out.

The workstation is ready. [Run the tests](run-the-tests.md) describes how to run them against
`targets/local.yml`.
