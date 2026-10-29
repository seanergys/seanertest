<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Write your first test

This tutorial writes a test in three steps. It starts with a PostgreSQL database, adds a logical
node with software built by Spack, and ends with the node talking to the database. Each step is run
on a local minikube cluster before the next one is added.

The tutorial assumes a workstation prepared as described in
[Set up a workstation](../how-to/set-up-a-workstation.md), with minikube running and the target
`targets/local.yml`. All commands run in the root of the seanertest checkout.

## 1. Create the test directory

Every test is a directory below `tests/`, named with a number and a short description. Create the
directory for this tutorial:

```bash
mkdir tests/006-my-first-test
```

If the number 006 is already taken, use the next free number in all following commands.

## 2. Start a database

The file `fixture.yaml` declares what the test needs. Create
`tests/006-my-first-test/fixture.yaml` with one service, a PostgreSQL database in its own
container:

```yaml
version: 2

services:
  - name: postgres
    driver: container
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: tutorial
    setup:
      - until pg_isready -U postgres; do sleep 1; done
    ports:
      - 5432
```

The `setup` command waits until the database accepts connections, so that the test does not start
too early. The port makes the database reachable from the test and from other pods.

Create `tests/006-my-first-test/test_main.py` with a test that runs a query in the database's
container:

```python
def test_postgres_answers(services):
    postgres = services["postgres"]

    output = postgres.exec(["psql", "-U", "postgres", "-Atc", "SELECT 1 + 1"])

    assert output.strip() == "2"
```

The `services` fixture starts the services of `fixture.yaml` and hands them to the test by name.
Run the test:

```bash
uv run pytest -v -s --target local --cache-dir ~/.cache/seanertest tests/006-my-first-test
```

The output ends with:

```text
tests/006-my-first-test/test_main.py::test_postgres_answers PASSED
```

## 3. Add a node with software

Services such as Flux run on logical nodes, which are pods whose software comes from a Spack
environment. Create `tests/006-my-first-test/spack.yaml` with one package:

```yaml
spack:
  specs:
    - m4@1.4.19
  view: true
```

Add a `nodes` block and a second service to `fixture.yaml`. The `environment` driver installs the
environment on the nodes of the role `tools` without starting a service. The file now reads:

```yaml
version: 2

nodes:
  - role: tools
    count: 1

services:
  - name: postgres
    driver: container
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: tutorial
    setup:
      - until pg_isready -U postgres; do sleep 1; done
    ports:
      - 5432

  - name: tools
    driver: environment
    roles: [tools]
    software:
      spack: spack.yaml
```

Add a test to `test_main.py` that runs `m4` on the node:

```python
def test_node_has_m4(services):
    tools = services["tools"]

    output = tools.exec(["m4", "--version"])

    assert "(GNU M4) 1.4.19" in output
```

Run the tests again with the same command. This time, seanertest first builds the environment and
prints the lines of the build container with the prefix `[build]`:

```text
seanertest: building 1 environment(s) for x86_64 in docker.io/rockylinux/rockylinux:10
```

The compiler comes ready-built from the SEANERGYS registry, so only `m4` and its dependencies are
built, which takes a few minutes. The pod of the node then installs the binaries:

```text
seanertest: installing environment 64f7b5074f722d5d on minikube
tests/006-my-first-test/test_main.py::test_postgres_answers PASSED
tests/006-my-first-test/test_main.py::test_node_has_m4 PASSED
```

Run the command once more. The environment is now in the cache directory, and the build phase
reports `seanertest: all environments are already built`.

## 4. Connect the node to the database

Inside the test's namespace, every pod reaches a container service under its name. Add a test that
opens a connection from the node to port 5432 of `postgres`:

```python
def test_node_reaches_postgres_by_name(services):
    tools = services["tools"]

    output = tools.exec("exec 3<>/dev/tcp/postgres/5432 && echo connected")

    assert "connected" in output
```

Run the tests a last time. All three pass:

```text
tests/006-my-first-test/test_main.py::test_postgres_answers PASSED
tests/006-my-first-test/test_main.py::test_node_has_m4 PASSED
tests/006-my-first-test/test_main.py::test_node_reaches_postgres_by_name PASSED
```

## What the test did not say

The fixture names no host, no node size and no cache. On a multi-node testbed, the same directory
runs unchanged: seanerops places the node `tools-0` on a host of its own, and the pods install the
environment from the testbed's registry cache instead of the cache server on the workstation.

## Clean up

The tutorial test is not meant for the repository. Remove it:

```bash
rm -r tests/006-my-first-test
```

To add a real test, follow [Add a test](../how-to/add-a-test.md), which adds the licence headers
and the checks that CI expects.
