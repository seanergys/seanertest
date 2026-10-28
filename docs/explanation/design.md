<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Design

This page describes the intended setup of seanertest and how it works together with seanerops and
seanerstack. It records the decisions taken so far, the alternatives that were rejected, and the
questions that are still open. Most of the design is not yet implemented.

Seanertest and seanerops may be rewritten completely to follow this design. Backward compatibility
with their current interfaces is not a goal.

## Responsibilities

The aim is that tests describe only what they need, and that every fact about a testbed lives in
one place.

| Component | Responsibility | Status |
| --- | --- | --- |
| seanertest | Drives the complete run. It collects the selected tests, builds their node request, builds their software, obtains a testbed from seanerops, starts the services and runs the tests. | Decided |
| seanerops | Turns a node request into logical nodes on a target and provides the Kubernetes cluster. It decides placement, allocation mode and node sizes. | Decided |
| seanerstack | Provides the curated Spack recipes and the isolated Spack setup used to build the software. | Decided |

- **Tests never name a target:** A test states roles and node counts. Everything about a target,
  such as its hosts, sizes and cache, comes from the target description.
- **seanerops stays usable on its own:** It is a library with a thin command-line interface on top.
  Seanertest uses the library, and people can run the command-line interface standalone.

## Flow of a run

1. Seanertest collects the selected tests and reads their fixtures.
2. Seanertest runs the build phase. It installs every software environment of the selected tests
   and pushes the binaries to the target's build cache.
3. Seanertest groups the tests by their effective allocation mode. In the usual case there is one
   group.
4. For each group, seanertest merges the node requests of its tests and asks seanerops for a
   testbed.
5. Seanerops allocates logical nodes on the target and returns a testbed description.
6. Seanertest creates one pod per logical node. Each pod installs its software from the build cache
   and then starts its service.
7. The tests run.
8. Seanertest deletes the pods and releases the testbed.

## Targets

A target is a machine that tests run on, for example a laptop running minikube or the DEEP
testbed. Each target is described by one file, selected with `--target NAME`. The file contains
both the part used by seanerops and the part used by seanertest.

A single-node target:

```yaml
version: 1
name: laptop
architecture: x86_64

runtime:
  type: external
  kubeconfig: ~/.kube/config

nodes:
  - minikube

cache:
  type: http
  address: 192.168.49.1
```

A multi-node target:

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
    - dp-cn46

cache:
  type: oci
```

| Setting | Meaning | Status |
| --- | --- | --- |
| `architecture` | Selects the build settings described in [Software](#software). | Decided |
| `runtime.type` | `external` uses an existing cluster such as minikube. `k3s` lets seanerops deploy K3s. | Decided |
| `nodes` | The hosts of the target. On a multi-node target, the control node is not part of the allocation pool. On a single-node target, the only node is. | Decided |
| `allocation` | Optional. Overrides the default allocation mode and node size, see [Allocation](#allocation). | Decided |
| `cache.type` | `http` for single-node targets, `oci` for multi-node targets, see [Build caches](#build-caches). | Decided |
| `cache.address` | For `http` only. The host's address on the cluster's network. | Decided |

## Node requests

A test declares the nodes it needs in its fixture. Seanertest merges the declarations of the
selected tests into one request for seanerops. For each role, the merged request asks for the
largest count that any single test asks for.

```yaml
version: 1
allocation:
  mode: exclusive
nodes:
  - role: login
    count: 1
  - role: compute
    count: 4
```

| Field | Meaning | Status |
| --- | --- | --- |
| `nodes[].role` | A name chosen by the test. It is unique within the request. Seanerops does not interpret it. | Decided |
| `nodes[].count` | The number of logical nodes with this role. | Decided |
| `allocation.mode` | Optional. Overrides the target's default mode. It is a requirement, not a preference. | Decided |
| Unknown keys | Rejected by seanerops. | Decided |
| `resources` and `constraints` | Per-node requirements based on the node-level part of the Flux and Slurm request models. | Deferred |

- **No callbacks:** A request contains only data that seanerops can evaluate itself. A callback that
  runs after allocation could reject hosts that seanerops has already chosen.
- **Mode overrides:** A test that requires `exclusive` mode is skipped with a reason on a target
  that cannot provide enough hosts. `shared` mode can always be provided.
- **Grouping by mode:** A testbed has one mode. When the selected tests need different modes,
  seanertest runs one testbed after another, one per mode.

## Allocation

Seanerops places logical nodes on hosts in one of two modes.

| Mode | Placement | Default for | Status |
| --- | --- | --- | --- |
| `shared` | Several logical nodes run on one host. Oversubscription is allowed, so ten 1-CPU nodes can run on an 8-core machine. | Single-node targets | Decided |
| `exclusive` | Each logical node has a host to itself. If the pool has too few hosts, the request fails before anything is deployed. | Multi-node targets | Decided |

The default mode depends only on the target, never on the request. Otherwise selecting one more
test could change how every test on that target runs.

Each logical node receives Kubernetes resource requests and limits. Seanerops computes both, and
seanertest copies them unchanged into the pod.

| Value | `shared` | `exclusive` | Status |
| --- | --- | --- | --- |
| Requests | `10m` CPU and `64Mi` memory | `10m` CPU and `64Mi` memory | Decided |
| Limits | `allocation.node`, by default 1 CPU and `4Gi` memory | `allocation.node`, by default the host's allocatable CPU and memory | Decided |

- **Small requests:** Kubernetes schedules by requests. Small requests allow oversubscription in
  `shared` mode and never block placement in `exclusive` mode, where seanerops already guarantees
  one logical node per host.
- **Both values are always set:** If a pod sets only limits, Kubernetes copies them into the
  requests, which would prevent oversubscription.
- **Memory oversubscription:** In `shared` mode the memory limits can add up to more than the host
  has. If tests really use that much memory at the same time, pods are killed, and seanertest
  reports `OOMKilled` clearly.

## Testbed description

Seanerops describes the allocated testbed in `testbed.json`. As a library it returns the same data
as a Python object.

```json
{
  "version": 1,
  "name": "laptop",
  "allocation": {"mode": "shared"},
  "nodes": [
    {
      "name": "compute-0",
      "roles": ["compute"],
      "host": "minikube",
      "resources": {
        "requests": {"cpu": "10m", "memory": "64Mi"},
        "limits": {"cpu": "1", "memory": "4Gi"}
      }
    }
  ]
}
```

| Field | Meaning | Status |
| --- | --- | --- |
| `allocation.mode` | The mode that was used. It is recorded so that test reports show it. | Decided |
| `nodes[].name` | The logical node name. It becomes the pod's host name. | Decided |
| `nodes[].roles` | A list with exactly one role. It is a list so that a later version can allow several roles per node. | Decided |
| `nodes[].host` | The Kubernetes node that the logical node runs on. | Decided |
| `nodes[].resources` | The requests and limits for the pod. | Decided |

- **Compatibility:** Consumers ignore fields they do not know. Adding an optional field keeps
  version 1. Removing a field or changing its meaning requires a new version.
- **Schema:** The HPC System Description Schema was considered and rejected, because it describes
  node types and counts but not individual hosts.

## Pods and host names

Seanertest creates one pod for each logical node.

- **Placement:** The pod is pinned to its host with the `kubernetes.io/hostname` label.
- **Host name:** The pod's host name is the logical node name. A headless Service makes the names
  resolvable within the test namespace.
- **Services see these names:** Seanertest passes the host names, together with their roles, to the
  services. Flux, for example, receives the list of broker host names and the role of each.
- **Isolation:** Each test module gets its own namespace, which is deleted at the end. Pod logs and
  events are collected when a test fails.
- **Readiness:** A pod counts as ready only when its software is installed and its service has
  started.

## Fixtures

A fixture declares the nodes of the test once, at fixture level. Each service then names the roles
it runs on.

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

- **Service drivers:** A generic layer handles placement, pods and lifecycle. Each service driver
  only renders its configuration, starts its processes, checks readiness and returns the object the
  test uses.
- **Container services:** Services such as PostgreSQL and SeaweedFS keep their own images. The
  `container` driver runs them as ordinary pods. They are not part of the node request.
- **No target-specific files:** Fixtures contain no per-target configuration. The current
  `configs/<target>/` directories and `hosts.yaml` files are removed.
- **No operators:** Per-service Kubernetes operators, such as the Flux Operator, are not used,
  because there are many services and each would bring its own deployment model.

## Software

All software of the services under test is built with Spack, through seanerstack, and installed in
the pods from a build cache. No custom images are built, because only approved images may run.

### Architectures

Targets are divided into a small number of architectures. Each architecture is built once and
serves every target of that architecture.

| Architecture | Image | Spack target | Status |
| --- | --- | --- | --- |
| `x86_64` | Rocky Linux 10 | `x86_64_v3` | Decided |
| `aarch64` | Rocky Linux 10 | To be decided | Not yet implemented |

- **Generic targets:** Building for a generic level such as `x86_64_v3` rather than a specific CPU
  lets one build serve all machines of an architecture.
- **Builder hosts:** An x86 host can build for any x86 target. Building for `aarch64` requires an
  `aarch64` host, because emulation is too slow.

### Spack, recipes and compiler

| Item | Decision | Status |
| --- | --- | --- |
| Spack | The build container and every pod install Spack themselves, at the same pinned version. | Decided |
| Recipes | Only recipes from the builtin `spack-packages` repository are used for now, including Flux. Seanerstack's own recipes are not used yet. | Decided |
| Compiler | The build container uses seanerstack's compiler bootstrap. The bootstrapped compiler is built with the image's system compiler, and its runtime reaches the pods through the build cache. | Decided |
| Pinning | The Spack version and the `spack-packages` commit are pinned and identical in the build container and in the pods. | Decided |

- **Why pinning matters:** A binary in the build cache is used only when its hash matches exactly.
  The hash depends on the recipes, so a pod that uses a newer `spack-packages` commit than the build
  container would find no matching binaries.
- **No system compiler in pods:** Pods install ready-built binaries only, so they need no compiler.

### Build phase

The build phase runs before any testbed is requested and before any test starts.

1. Seanertest collects the `spack.yaml` files of the selected tests.
2. It starts a build container from the architecture's image, with the cache directory mounted.
3. It creates one Spack environment for each distinct `spack.yaml`, all in one Spack instance, and
   concretizes them for the architecture's target.
4. It installs the environments one after another, each with all cores of the host.
5. It pushes the binaries to the build cache and keeps each environment's lock file.

- **One Spack instance:** All environments share one store, so packages that several environments
  need are built once.
- **Environments are not merged:** Two tests may pin different versions of the same package, and a
  merged environment would fail to concretize.
- **Tests never build:** Only the build phase runs `spack install` against the build cache. If the
  build phase fails, the run stops before any testbed exists.

### Build caches

| Target | Cache | Written by | Read by pods through | Status |
| --- | --- | --- | --- | --- |
| Single node | A directory on the host, chosen with `--cache-dir` | The build phase, through Spack's `autopush` | HTTP, served by seanertest | Decided |
| Multiple nodes | The OCI registry | The build phase | The registry, with a read-only token | Not yet implemented |

The filesystem cache is not used to fill the OCI cache.

The single-node cache is served over HTTP while the session runs.

- **Server:** Seanertest serves the cache directory read-only from a thread inside the pytest
  process. The server stops with the process, so nothing is left running.
- **Address:** The server binds to the host's address on the cluster's network, given as
  `cache.address` in the target description. With minikube's Docker driver this is the gateway of
  the `minikube` Docker network. The address is reachable from the host and from the cluster, but
  not from other machines.
- **Loopback does not work:** Pods cannot reach the host's `127.0.0.1`, because each pod and the
  minikube node have their own network namespaces.
- **Missing address:** If the configured address does not exist on the host, seanertest stops at
  startup instead of binding to every interface.
- **Path token:** The cache is served below a random path segment for each session, so other
  containers on the same network cannot browse it.

For multi-node targets, seanertest stores the read-only registry token in a Kubernetes Secret in the
test namespace. Pods receive it through the `SEANERSTACK_RESOURCE_*` variables, and it is deleted
with the namespace.

### Installation in pods

- **From the lock file:** Pods install from the lock file of the build phase with
  `spack install --use-buildcache only`. They never concretize again, so a hash mismatch fails at
  once instead of starting a build.
- **Once per host:** One installer per host installs into a directory on that host, and the other
  pods on the host use it. This prevents many pods on one host from installing at the same time.

### Cache directory

Seanertest keeps its persistent data in one directory, given with `--cache-dir` or
`SEANERTEST_CACHE_DIR`.

```text
<cache-dir>/
├── buildcache/
└── source-cache/
```

If no directory is given, seanertest uses a temporary directory, removes it at the end of the
session, and prints a notice that built packages will not be reused. A build cache can grow to many
gigabytes, so the user decides where it is kept.

## Concurrency

- **Within a run:** The build phase installs one environment at a time, and tests start only after
  it has finished.
- **Between runs:** Only one seanertest instance runs per machine at a time. In CI this is enforced
  by the runner's concurrency settings, for example `resource_group` in GitLab CI. Developers run
  seanertest on their own machines.
- **No locks:** Because of these two rules, seanertest does not lock the cache directory.

## Rejected alternatives

| Alternative | Reason | Status |
| --- | --- | --- |
| Flux Operator and other per-service operators | Many services would each bring their own deployment model. | Rejected |
| Callbacks in node requests | Seanerops cannot evaluate them when it chooses hosts. | Rejected |
| HPC System Description Schema for `testbed.json` | It does not describe individual hosts. | Rejected |
| Switching the allocation mode automatically when a request does not fit | The same target would behave differently depending on the selected tests. | Rejected |
| Raising the advertised capacity of Kubernetes nodes | The kubelet reports the real capacity and overwrites changes. | Rejected |
| Merging all environments into one | Pinned versions can conflict. | Rejected |
| Building custom images | Only approved images may run. | Rejected |
| Mounting the cache into minikube with `minikube mount` | Serving it over HTTP needs no external process and works on any cluster. | Rejected |
| Binding the cache server to `127.0.0.1` | Pods cannot reach the host's loopback interface. | Rejected |

## Open questions

| Question | Notes | Status |
| --- | --- | --- |
| How do the lock files reach the pods? | In `http` mode they can be served together with the cache. In `oci` mode they need another channel. | Open |
| Where do the build container and the pods fetch the pinned Spack and `spack-packages` from? | Fetching from GitHub needs network access from every pod. Serving them together with the cache avoids that in `http` mode. | Open |
| Does the Rocky Linux 10 image contain the tools Spack needs? | For example Python, `git`, `tar` and the compression tools. Missing tools would have to be installed when the container starts. | Open |
| Does seanerstack support pinning the `spack-packages` commit? | It currently configures the builtin repository from `spack-packages` without a pinned commit. | Open |
| Which credentials does the build phase use to push to the OCI cache? | Writing requires a token with write access, which only CI should hold. | Open |
| Which Spack target is used for `aarch64`? | Decided together with the `aarch64` builder host. | Deferred |
| Should `shared` mode check capacity against the hosts' allocatable resources? | Without a check, pods that do not fit stay `Pending` until the readiness timeout. | Deferred |
| Should a request allow a different mode for each role? | Not needed so far. | Deferred |

## Implementation order

1. **seanerops:** Library and command-line interface, target descriptions, node requests,
   allocation in both modes, `testbed.json`, and the `external` runtime for existing clusters.
2. **seanertest:** Build phase, cache directory, and the HTTP cache server.
3. **seanertest:** Kubernetes backend with one pod per logical node, installation from the build
   cache, and the testbed lifecycle.
4. **seanertest:** Fixture version 2, the Flux driver ported to the new backend, and the `container`
   driver.
5. **seanertest:** Continuous integration with the matrix derived from targets, and removal of the
   current Docker machine provider.
6. **seanerops and seanertest:** OCI build cache for multi-node targets.
