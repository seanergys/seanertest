<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# How-to guides

Each guide gives the one supported procedure for a task. The guides assume that seanertest is set
up as described in [Set up a workstation](set-up-a-workstation.md). The complete list of settings
behind each step is in the [reference](../reference/index.md).

| Guide | Task |
| --- | --- |
| [Set up a workstation](set-up-a-workstation.md) | Prepare a machine to run seanertest against a local minikube cluster. |
| [Run the tests](run-the-tests.md) | Run all tests, one test or one test function, and keep the build cache. |
| [Add a test](add-a-test.md) | Add a new numbered integration test to the repository. |
| [Give a test software from Spack](use-spack-software.md) | Install packages on the logical nodes of a test. |
| [Add a container service](add-a-container-service.md) | Run a service with its own image, such as PostgreSQL, next to the nodes. |
| [Run Flux on the logical nodes](run-flux.md) | Start a Flux instance across the nodes of a test and submit jobs to it. |
| [Build the compiler](build-the-compiler.md) | Build `gcc@15` once and share it through the registry. |
| [Set up the CI runner](set-up-the-ci-runner.md) | Prepare the VM that runs the integration tests in GitLab CI. |
