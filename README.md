<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# seanertest

Seanertest runs integration tests for SEANERGYS services on testbeds. It is a pytest plugin that
drives the complete run: it builds the software of the selected tests with seanerstack, obtains a
testbed from seanerops, starts the services in Kubernetes pods, and runs the tests against them.

## Design

- **Targets:** A target is a machine that tests run on, described by one file in `targets/`. The
  same test runs unchanged on every target.
- **Fixtures:** Each test directory has a `fixture.yaml` that declares the logical nodes the test
  needs and the services that run on them.
- **Build phase:** Before any test starts, seanertest builds every Spack environment of the
  selected tests in the approved Rocky Linux 10 image and pushes the binaries to the target's build
  cache.
- **Pods:** Every logical node is a pod whose host name is the logical node name. The pods install
  their software from the build cache and never build anything.

The [design document](docs/explanation/design.md) explains the responsibilities of seanertest,
seanerops and seanerstack in detail.

## Running tests

The tests need a Kubernetes cluster, Docker for the build container, and access to GitHub and the
SEANERGYS GitLab. For a local minikube cluster with the Docker driver:

1. Start minikube:

    ```bash
    minikube start
    ```

2. Write a target for it. The script finds the address of the host on minikube's network:

    ```bash
    scripts/minikube-target.sh minikube ~/.kube/config > targets/local.yml
    ```

3. Run the tests and keep the build cache between runs:

    ```bash
    uv run pytest -v -s --target local --cache-dir ~/.cache/seanertest
    ```

Pods reach the build cache over HTTP on the host's address in minikube's network. If the host's
firewall drops inbound traffic, as ufw does by default, give the target a fixed port and allow it
from the minikube network:

```bash
scripts/minikube-target.sh minikube ~/.kube/config 18080 > targets/local.yml
sudo ufw allow in from 192.168.49.0/24 to 192.168.49.1 port 18080 proto tcp
```

Without `--cache-dir`, seanertest uses a temporary directory and builds everything again in the
next run. The first run builds the compiler and every environment, which takes a long time; later
runs install binaries from the cache.

| Option | Environment variable | Meaning |
| --- | --- | --- |
| `--target` | `SEANERTEST_TARGET` | A target file, or a name that refers to `targets/NAME.yml`. |
| `--cache-dir` | `SEANERTEST_CACHE_DIR` | Directory that keeps the build cache and downloaded sources. |
| `--seanertest-config` | | The configuration file; by default `config.yml`, found upward from the tests. |

Seanerstack is installed in the build container from the SEANERGYS GitLab. If that needs
credentials, set `SEANERTEST_GIT_TOKEN`, and optionally `SEANERTEST_GIT_USERNAME`. To install it from
a local checkout instead, set `SEANERTEST_SEANERSTACK_SRC` to the checkout.

Registry credentials come from `docker login registry.seanergys.fz-juelich.de`, or from
`SEANERTEST_OCI_USERNAME` and
`SEANERTEST_OCI_PASSWORD` for a target's OCI cache and `SEANERTEST_UPSTREAM_USERNAME` and
`SEANERTEST_UPSTREAM_PASSWORD` for the upstream caches in `config.yml`. Log in without a port:
Docker stores logins by the exact host name, so a login for `registry.seanergys.fz-juelich.de:443`
is not used for `registry.seanergys.fz-juelich.de`, and the registry then answers with
`access forbidden`.

## Building the compiler once

Bootstrapping the compiler, `gcc@15`, takes hours, while the environments of the tests build in
minutes once the compiler is available. The compiler is therefore built once, on a strong machine,
and shared through the seanerstack build cache in the SEANERGYS registry, which `config.yml` lists
as an upstream cache. Test sessions install it from there and build their environments themselves.

1. Log in with an account that may write to the registry:

    ```bash
    docker login registry.seanergys.fz-juelich.de
    ```

2. Build the compiler and push it:

    ```bash
    scripts/build-compiler.sh
    ```

The script needs Docker, uv and a seanerstack checkout, by default the one next to this checkout;
`SEANERSTACK_SRC` selects another. It runs `python -m seanertest.build --compiler-only`, which runs
the build script of a session without environments, so the compiler gets the same hash as in every
test session. `python -m seanertest.build FIXTURE...` builds environments the same way.

## Writing a test

A test directory contains `test_main.py`, `fixture.yaml`, and the files the fixture refers to:

```yaml
version: 2

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

  - name: postgres
    driver: container
    image: postgres:16-alpine
    ports: [5432]
```

| Driver | Runs on | Purpose |
| --- | --- | --- |
| `flux` | Logical nodes | One Flux broker per logical node of the given roles. |
| `environment` | Logical nodes | The installed Spack environment without a running service. |
| `container` | Its own pod | A service that keeps its own image, such as PostgreSQL. |

- **Allocation:** A fixture may require a mode with `allocation: {mode: exclusive}`. A test whose
  requirement the target cannot meet is skipped with the reason.
- **Flux options:** `options.login` names the role of the login node, by default `login`.
  `options.schedulable` lists the roles that run jobs, by default `[compute]`.
- **Test handles:** Tests receive the services through the `services` fixture, for example
  `services["seanergys.flux"].exec([...])`. Container services provide `endpoint(port)`.

## Repository structure

```text
config.yml
targets/
scripts/
src/seanertest/
tests/
docs/
```

- **`config.yml`:** Software sources, the approved image and Spack target per architecture, the
  compiler, and the system packages installed in the containers.
- **`targets/`:** Target descriptions.
- **`tests/`:** Integration tests, and the `selftest-*` directories that test seanertest itself
  without a cluster.

## Continuous integration

The jobs run on a runner with the tags `shell`, `testbed`, `generic` and `micro`, which provides
Docker, minikube and uv. A job runs only on a runner that has all of its tags. To prepare a
Rocky Linux 10 VM as that runner, run `scripts/setup-shell-runner.sh` as root on the VM. It
installs Docker, minikube, kubectl, uv, Git and gitlab-runner, gives the runner user access to
Docker, and opens the build cache port to the minikube network. Registering the runner with GitLab
stays a manual step, and the script prints the command for it.

| Job | Purpose |
| --- | --- |
| `selftest` | Runs the self-tests. |
| `integration:minikube` | Starts a minikube profile, writes a target for it, and runs the integration tests. |

## Documentation

Build and serve the documentation locally with:

```bash
uv run --no-project --with "properdocs>=1.6.7" --with "mkdocs-materialx>=10.2.0" properdocs serve
```
