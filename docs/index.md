<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# seanertest

Seanertest runs integration tests for SEANERGYS services on testbeds. It is a pytest plugin that
drives the complete run: it builds the software of the selected tests with seanerstack, obtains a
testbed from seanerops, starts the services in Kubernetes pods, and runs the tests against them.

A test is a directory with a `test_main.py` and a `fixture.yaml`. The fixture states what the test
needs, such as two compute nodes with Flux and a PostgreSQL database, and never names a machine.
The same test therefore runs unchanged on a laptop with minikube and on a multi-node testbed.

```text
tests/004-flux-submits-two-jobs/
    fixture.yaml
    flux.toml
    spack.yaml
    test_main.py
```

## How these docs are organized

The documentation follows four kinds of pages, each with one purpose.

| Section | Purpose | Start here when |
| --- | --- | --- |
| [Tutorials](tutorials/index.md) | Learning by doing, from an empty workstation to a passing test. | You have not used seanertest before. |
| [How-to guides](how-to/index.md) | One canonical procedure for each task, such as adding a test. | You know what you want to do. |
| [Reference](reference/index.md) | The complete description of every file format, option and test handle. | You need the exact name or meaning of a setting. |
| [Explanation](explanation/index.md) | Why seanertest works the way it does, and what was decided. | You want to understand or change the design. |

## Components

| Component | Responsibility |
| --- | --- |
| seanertest | Drives the run: collects the tests, builds their software, starts their services and runs them. |
| seanerops | Turns a node request into logical nodes on a target and provides the Kubernetes cluster. |
| seanerstack | Provides the curated, isolated Spack setup that builds the software. |
