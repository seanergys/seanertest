<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Fixture file

Every test directory contains a `fixture.yaml`, which declares the logical nodes the test needs and
the services that run for it. Unknown keys are rejected at every level, and paths are relative to
the test directory and may not leave it.

```yaml
version: 2

allocation:
  mode: exclusive

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
    options:
      login: login
      schedulable: [compute]

  - name: postgres
    driver: container
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: example
    setup:
      - until pg_isready -U postgres; do sleep 1; done
    ports: [5432]
```

## Top level

| Key | Required | Meaning |
| --- | --- | --- |
| `version` | Yes | The format version. Only `2` is supported. |
| `nodes` | For node services | The logical nodes, as a list of roles and counts. |
| `allocation` | No | A required allocation mode, `{mode: shared}` or `{mode: exclusive}`. Without it, the target decides. |
| `services` | Yes | A non-empty list of services. |

- **Roles:** A role is a DNS label of at most 50 characters, such as `compute`. The nodes of a role
  are named `<role>-<index>`, starting at 0, and that name is the host name of the node's pod.
- **Counts:** A count is a positive integer and is the same on every target.
- **Allocation modes:** In the `shared` mode, logical nodes share hosts. In the `exclusive` mode,
  every logical node has a host of its own. A test whose mode the target cannot provide is skipped.

## Services

| Key | Drivers | Required | Meaning |
| --- | --- | --- | --- |
| `name` | All | Yes | The name under which the test receives the service. Unique in the fixture. |
| `driver` | All | Yes | `flux`, `environment` or `container`. |
| `roles` | `flux`, `environment` | Yes | The roles of the logical nodes that the service runs on. Each must be declared in `nodes`. |
| `software` | `flux`, `environment` | Yes | `{spack: FILE}`, the Spack environment installed on the nodes. All node services of a fixture name the same file. |
| `config` | `flux` | No | A Flux configuration file in TOML, without the `[bootstrap]` and `[resource]` tables. |
| `options` | `flux`, `environment` | No | Driver options. The `environment` driver takes none. |
| `config` | `container` | No | A configuration file, mounted at `/etc/seanertest/<file name>`. `SEANERTEST_CONFIG` holds that path. |
| `image` | `container` | Yes | The image of the service. |
| `command` | `container` | No | Replaces the image's command. A list of arguments, or a string run with `/bin/sh -c`. |
| `entrypoint` | `container` | No | Replaces the image's entrypoint, in the same forms as `command`. |
| `environment` | `container` | No | Environment variables, as a mapping. |
| `ports` | `container` | No | TCP ports that the service listens on. They are published to the test and to the other pods. |
| `files` | `container` | No | Files to mount, as a list of `{source: FILE, target: ABSOLUTE_PATH}`. |
| `setup` | `container` | No | Shell commands, run in order in the service's pod after it has started and before the tests. |

## Drivers

| Driver | Runs on | Result |
| --- | --- | --- |
| `flux` | The logical nodes of its roles | One Flux broker per node, joined into one instance. |
| `environment` | The logical nodes of its roles | The installed Spack environment without a running process. |
| `container` | A pod of its own | The image's process, with the given ports published. |

## Flux options

| Option | Default | Meaning |
| --- | --- | --- |
| `login` | `login` if the service has that role, otherwise its first role | The role whose first node runs the commands of `exec`. |
| `schedulable` | `[compute]` if the service has that role, otherwise all of its roles | The roles whose nodes run jobs. |
