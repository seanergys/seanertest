<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Target file

A target file describes one machine that tests run on. `--target NAME` selects
`targets/NAME.yml`, and `--target PATH` selects any file. The format belongs to seanerops, which
also reads it on its own; seanertest additionally requires a `cache`.

```yaml
version: 1
name: deep
architecture: x86_64

runtime:
  type: k3s
  data_dir: /scratch/k3s

nodes:
  control:
    - dp-cn43
  workers:
    - dp-cn44
    - dp-cn45

allocation:
  mode: exclusive

cache:
  type: oci
  url: oci://registry.seanergys.fz-juelich.de/software/seanertest/buildcache
```

| Key | Required | Meaning |
| --- | --- | --- |
| `version` | Yes | The format version. Only `1` is supported. |
| `name` | Yes | The target's name, which tests receive through the `testbed` fixture. |
| `architecture` | Yes | An architecture of `config.yml`, which selects the image and the Spack target. |
| `runtime.type` | Yes | `external` for an existing cluster with `runtime.kubeconfig`, or `k3s` for a cluster that seanerops deploys. |
| `nodes` | Yes | A list with one host for a single-node target, or `control` with one host and `workers` with at least one host for a multi-node target. |
| `allocation.mode` | No | `shared` or `exclusive`. The default is `shared` on a single-node target and `exclusive` on a multi-node target. |
| `allocation.node.cpu`, `allocation.node.memory` | No | The size of a logical node in the shared mode, by default `1` and `4Gi`. |
| `cache.type` | For seanertest | `http` on a single-node target, `oci` on a multi-node target. |
| `cache.address` | For `http` | The host's address on the cluster's network, at which the pods reach the cache server. |
| `cache.port` | No | For `http`, a fixed port of the cache server. Without it, a free port is chosen for every session. |
| `cache.url` | For `oci` | The registry path of the build cache. |

- **Pool:** On a multi-node target, the control host runs the Kubernetes control plane and is not
  part of the allocation pool. On a single-node target, the only host is.
- **Exclusive nodes:** In the exclusive mode, a logical node gets one host, and its CPU and memory
  limits are the host's allocatable resources.

The seanerops documentation describes the runtimes and their settings in full.
