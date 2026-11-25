<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# How a run works

The aim of seanertest is that a test describes only what it needs, and that every fact about a
machine lives in one place, the target file. A test asks for two compute nodes with Flux, and the
same request is met by two pods on a laptop or by two hosts of a testbed. This page follows one
run from the `pytest` command to the deleted pods and explains why each step is placed where it is.

## From collection to the first test

1. **Collection:** pytest collects the selected test modules. For every module with a
   `fixture.yaml` beside it, seanertest reads the fixture and rejects invalid ones before anything
   is started.
2. **Build phase:** Seanertest builds the Spack environments of all selected tests in one build
   container, before any test starts. It skips environments that the cache directory already
   holds, and it pushes the binaries to the target's build cache.
3. **Grouping:** The tests are ordered by their effective allocation mode, so that each group needs
   one testbed. Usually there is one group.
4. **Testbed:** For each group, seanertest merges the node requests of its tests, taking the largest
   count of each role, and asks seanerops for a testbed. Seanerops places the logical nodes on the
   target's hosts and returns their names, hosts and sizes.
5. **Services:** When the first test of a module asks for `services`, seanertest creates a
   Kubernetes namespace for the module. It installs the environment on every host that carries a
   logical node, starts one pod per logical node and one pod per container service, and lets the
   drivers start the services.
6. **Tests:** The test functions of the module run against the running services.
7. **Cleanup:** After the last test of the module, the namespace is deleted with all its pods. After
   the last group, the testbed is released.

## Why the software is built first

Building software inside a test would make the test's duration depend on the state of the cache,
and several tests would build the same packages at the same time. The build phase builds each
environment once per run, in one Spack instance, and the pods only install ready-built binaries.
A pod therefore never needs a compiler, and a test starts in seconds once its environment is in the
cache.

The build container and every pod use the same approved image, the same Spack commit and the same
`spack-packages` commit. A binary in a build cache is used only when its hash matches exactly, and
the hash depends on all of these.

## Why the compiler comes from the registry

The environments are built with `gcc@15`, which seanerstack bootstraps. Bootstrapping it takes
hours, so it is built once and kept in the seanerstack build cache in the SEANERGYS registry, an
upstream cache of `config.yml`, together with the lockfile that names it. Seanerstack's bootstrap
installs the compiler of that lockfile, so a new cache directory, such as that of a new CI runner,
installs the compiler in seconds. Whatever a build has to build from source is pushed back to that
cache, so that the next build on any machine installs it as well.

## Why each test module gets its own namespace

A namespace holds the pods of exactly one test module. Two modules can therefore use the same
service names and node names without interfering, and deleting the namespace removes everything
the module started. The logical node names, such as `compute-0`, are the host names of their pods,
and services such as Flux are configured with exactly these names. A test sees the same host names
on every target.

## Why a test never names a target

A fixture states roles and counts, and optionally a required allocation mode. It never names a
host, a node size or a cache. Placement and sizes are decided by seanerops from the target file, and
the allocation mode defaults to what suits the target: shared on a single host, exclusive on a
multi-node testbed. The same test thus runs in CI on a single minikube host and on a testbed with
one host per node, and a test that cannot be met by a target is skipped with the reason instead of
failing.
