<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Test API

Tests use two pytest fixtures, which the seanertest plugin provides. Both have module scope.

| Fixture | Value |
| --- | --- |
| `services` | A read-only mapping from the service names of `fixture.yaml` to running service handles. The services start before the first test of the module and stop after the last one. |
| `testbed` | The name of the selected target, such as `minikube`. |

An unknown name in `services` raises a `KeyError` that lists the available names. The classes
below can be imported from `seanertest` for type checks:

```python
from seanertest import ContainerService, FluxService, Service, Services
```

## Commands

Every `exec` method takes a command either as a list of arguments, which runs without a shell, or
as a string, which runs with a shell. It returns the standard output of the command. A command that
exits with another status than 0 raises a `RuntimeError` whose message contains the exit status,
the standard output and the standard error.

## `ContainerService`

The handle of a service with the `container` driver.

| Member | Meaning |
| --- | --- |
| `exec(command)` | Runs the command in the service's pod. A string runs with `/bin/sh -c`. |
| `endpoint(port, scheme="http")` | The URL at which the pytest process reaches the given container port, such as `http://192.168.49.2:31234`. |
| `host_port(port)` | The port on `address` that reaches the given container port. Raises `KeyError` for a port not listed in `ports`. |
| `address` | The address of the cluster host on which the ports are published. |
| `logs()` | The log of the service's container. |

## `FluxService`

The handle of a service with the `flux` driver.

| Member | Meaning |
| --- | --- |
| `exec(command)` | Runs the command on the login node, with the Spack environment activated and `FLUX_URI` set to the instance. |
| `broker_nodes()` | The nodes of all brokers, in rank order. |
| `compute_nodes()` | The nodes that run jobs. |
| `login_node()` | The node that runs the commands of `exec`. |
| `hostnames()` | The host names of the brokers, in rank order, such as `("login-0", "compute-0")`. |
| `login_address()` | The host name of the login node. |
| `flux_uri()` | The URI of the instance inside the login node's pod. |
| `pyflux()` | A handle of the Flux Python bindings when the pytest process can reach the instance, otherwise `None`. With the current local URI it is always `None`. |

## Environment service

The handle of a service with the `environment` driver.

| Member | Meaning |
| --- | --- |
| `exec(command)` | Runs the command on the first node of the service, with the Spack environment activated. A string runs with `/bin/bash -c`. |
| `nodes()` | The nodes of the service. |

## Nodes

The node methods of the service handles return one object per logical node.

| Member | Meaning |
| --- | --- |
| `name`, `hostname` | The logical node name, such as `compute-0`, which is also the pod's host name. |
| `role` | The role of the node. |
| `host` | The cluster host that runs the node's pod. |
| `exec(command, environment=None)` | Runs the command on the node with the Spack environment activated and the given variables set. A string runs with `/bin/bash -c`. |
| `exec_detached(command, environment=None)` | Starts the command in the background and returns at once. |
| `put_bytes(path, data, mode=0o444)` | Writes a file on the node. |
| `read_bytes(path)` | Reads a file from the node. |

Inside the namespace of a test, a node is reachable from the other pods as `<name>.nodes`, for
example `compute-0.nodes`.
