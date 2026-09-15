# seanertest fixture prototype

This is the minimal pytest + `fixture.yaml` + Docker implementation.

Each test lives in its own directory. The pytest `services` fixture finds the
`fixture.yaml` beside the test file, starts the declared service containers,
waits for published TCP ports to accept connections, yields a mapping of
service names to running service handles, and tears everything down afterwards.

```text
tests/
└── alpha/
    ├── fixture.yaml
    ├── c.yml
    └── test_alpha.py
```

A fixture looks like this:

```yaml
version: 1
services:
  - name: alpha
    image: python:3.12-alpine
    config: c.yml
    ports:
      - 8080
```

`config` is resolved relative to the test directory. It is copied into the
container at `/tmp/seanertest/config.yml` and the service receives
`SEANERTEST_CONFIG=/tmp/seanertest/config.yml`.

The file is copied through the Docker API rather than bind-mounted. This is
important for GitLab DinD, where the pytest job filesystem is not the Docker
daemon filesystem.

Services are attached to a private Docker network. Their fixture `name` is also
a network alias, so services can address each other by names such as `alpha`.
Published ports are assigned random host ports. Tests should use:

```python
alpha = services["alpha"]
url = alpha.endpoint(8080)
```

With DinD, `endpoint()` automatically uses the hostname from `DOCKER_HOST`
(`docker` in the included GitLab job); with a local Unix Docker socket it uses
`127.0.0.1`.

If GitLab registry variables are present, the fixture logs the Docker client in
to `CI_REGISTRY` before pulling images, so private project/group images can be
used directly in `fixture.yaml`.

## Flux Core example

`tests/flux-core/` declares a single Flux Core container and nothing else:

```yaml
version: 1

services:
  - name: flux-core
    image: fluxrm/flux-core:latest
    command:
      - sleep
      - infinity
```

The test verifies only that the Flux Core executable is present:

```python
def test_flux_core_is_available(services):
    flux = services["flux-core"]
    output = flux.exec(["flux", "--version"])
    assert "flux-core" in output
```

No Flux scheduler, broker configuration, ports, or service configuration are added yet.

## Multiple files and a prepared environment

A service can copy any number of files from its test directory into the
container with `files:`. Each entry has a local `source` and an absolute
container `target`.

`tests/spack-environment/` uses two files to create and install a Spack
environment:

```yaml
version: 1

services:
  - name: spack
    image: spack/ubuntu-jammy:latest
    command:
      - sleep
      - infinity
    files:
      - source: spack.yaml
        target: /opt/seanertest/input/spack.yaml
      - source: prepare.sh
        target: /opt/seanertest/input/prepare.sh
    setup:
      - sh /opt/seanertest/input/prepare.sh
    activate: /tmp/seanertest/activate.sh
```

`setup:` commands run once after the container starts. In this example,
`prepare.sh` creates the Spack environment, concretizes it, installs the
packages, and writes the shell activation commands to
`/tmp/seanertest/activate.sh`.

When `activate:` is present, every later `Service.exec()` automatically sources
that script first. Tests therefore use software from the prepared environment
without repeating Spack activation:

```python
def test_spack_environment_is_available(services):
    spack = services["spack"]
    output = spack.exec(["hello", "--version"])
    assert "GNU Hello" in output
```

`files:`, `setup:`, and `activate:` are generic fixture features; they are not
specific to Spack.

## One CI job per test file

GitLab CI first discovers every `tests/**/test_*.py` file and generates a child
pipeline with one job per test file. Each generated job gets its own DinD service,
so Docker state and service containers are isolated between test files.

Within pytest, the `services` fixture is module-scoped. A test file therefore
starts its adjacent `fixture.yaml` once, shares those services between tests in
that file, and tears them down when the file completes.

For example, these files:

```text
tests/alpha/test_alpha.py
tests/flux-core/test_flux_core.py
tests/spack-environment/test_spack_environment.py
```

produce three independent CI jobs, each running only its own file.
