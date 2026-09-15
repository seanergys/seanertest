# seanertest fixture prototype

Seanertest is a pytest fixture layer for integration tests that need services on
machine-shaped testbeds. The repository now has two distinct concepts:

1. **machine descriptions** say which execution nodes exist and how they are
   provisioned;
2. **service drivers** install/start a logical service across those nodes.

The original one-container-per-service fixtures continue to work unchanged.
Driver-backed services use a selected machine description.

## Selecting a machine/testbed

Pass the machine name to pytest:

```bash
pytest -v --testbed Asys tests/flux-service/test_flux_service.py
pytest -v --testbed Bsys tests/flux-service/test_flux_service.py
```

`SEANERTEST_TESTBED=Asys` is also accepted. Seanertest searches upward from the
test directory for `machines/<name>.yaml`.

The included Docker-only machines are:

```text
machines/
├── Asys.yaml   # 4 control + 1 login + 6 compute nodes
└── Bsys.yaml   # 1 control + 1 login + 4 compute nodes
```

A machine description is intentionally service-independent:

```yaml
version: 1
name: Asys

provider:
  name: docker
  image: fluxrm/flux-core:latest
  command: [sleep, infinity]

nodes:
  - role: control
    count: 4
  - role: login
    count: 1
  - role: compute
    count: 6
```

For the Docker provider, every logical node becomes one container with a stable
hostname such as `asys-control-0` or `asys-compute-3`.

## Driver-backed fixtures

`tests/flux-service/fixture.yaml` declares one logical Flux service:

```yaml
version: 1

services:
  - name: seanergys.flux
    driver:
      name: flux
      config:
        generic:
          config: configs/generic/config.toml
          hosts: configs/generic/hosts.yaml
        Asys:
          config: configs/Asys/config.toml
          hosts: configs/Asys/hosts.yaml
        Bsys:
          config: configs/Bsys/config.toml
          hosts: configs/Bsys/hosts.yaml
```

The selected testbed chooses the matching entry. If a machine exists but there
is no exact service configuration, `generic` is used as the fallback.

Each testbed has two Flux inputs:

```text
configs/
├── generic/
│   ├── config.toml
│   └── hosts.yaml
├── Asys/
│   ├── config.toml
│   └── hosts.yaml
└── Bsys/
    ├── config.toml
    └── hosts.yaml
```

`config.toml` is ordinary Flux configuration. `hosts.yaml` is deliberately not
a concrete Flux host list. It maps machine roles onto Flux brokers and
resources, for example:

```yaml
version: 1
brokers:
  roles: [control, login, compute]
login:
  role: login
resources:
  - role: control
    cores: "0"
    properties: [control]
    schedulable: false
  - role: login
    cores: "0"
    properties: [login]
    schedulable: false
  - role: compute
    cores: "0"
    properties: [compute]
    schedulable: true
```

The Flux driver combines this host-independent template with the actual nodes
created by the machine provider and writes the concrete Flux `[bootstrap]` and
`[[resource.config]]` configuration. Control and login brokers participate in
the Flux instance but are excluded from scheduling; only compute nodes execute
normal jobs.

## Flux service API

Tests receive the service through the normal `services` fixture:

```python
flux = services["seanergys.flux"]
```

The Flux-specific handle exposes:

```python
flux.broker_nodes()    # allocated nodes running Flux brokers
flux.compute_nodes()   # schedulable compute nodes
flux.hostnames()       # broker hostnames in Flux rank order
flux.login_node()      # the selected login node
flux.login_address()   # login hostname/address
flux.flux_uri()        # Flux URI used inside the login node
flux.pyflux()          # real flux.Flux handle when host-side access is possible
flux.exec([...])       # execute a command from the login node in the Flux instance
```

For the Docker backend, the Flux local connector is a UNIX socket inside the
login container, so `pyflux()` normally returns `None`. The API is intentionally
optional so a future provider with a host-reachable Flux URI can return a real
`flux.Flux` object without changing tests.

The integration test submits one task to every compute node and expects output
of the form:

```text
hello from asys-compute-0
hello from asys-compute-1
...
```

## Existing single-container fixtures

Simple fixtures remain valid:

```yaml
version: 1
services:
  - name: alpha
    image: python:3.12-alpine
    config: c.yml
    ports: [8080]
```

These are still useful for component tests that do not need a machine-level
service driver.

## CI

The child-pipeline generator detects explicit testbed entries in a fixture's
`driver.config`. A test file using the Flux fixture therefore becomes two CI
jobs automatically:

```text
pytest:tests-flux-service-test_flux_service-Asys
pytest:tests-flux-service-test_flux_service-Bsys
```

Each invokes pytest with the corresponding `--testbed` argument and gets its
own DinD daemon/network.
