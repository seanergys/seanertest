<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Add a container service

Services such as PostgreSQL or an S3 store keep their own images. The `container` driver runs each
of them in a pod of its own, next to the logical nodes of the test. Container services are not part
of the node request and need no `nodes` block.

1. Add the service to `fixture.yaml`. Give the image with a fixed tag, the environment it needs,
   and the TCP ports it listens on:

    ```yaml
    services:
      - name: postgres
        driver: container
        image: postgres:16-alpine
        environment:
          POSTGRES_DB: seanergys
          POSTGRES_USER: seanergys
          POSTGRES_PASSWORD: seanergys-example-password
        ports:
          - 5432
    ```

2. If the service needs time after its pod has started, add `setup` commands. They run in the
   service's pod, one after another, before any test starts:

    ```yaml
        setup:
          - until pg_isready -U seanergys -d seanergys; do sleep 1; done
    ```

3. If the service needs files, mount them from the test directory with `files`, or give one
   configuration file with `config`, which is mounted below `/etc/seanertest/` and named by the
   environment variable `SEANERTEST_CONFIG`:

    ```yaml
        files:
          - source: init.sql
            target: /docker-entrypoint-initdb.d/init.sql
    ```

4. Override the command of the image with `command`, as a list of arguments or as one shell
   command, if the image does not start the service as the test needs it. This S3 store listens on
   all addresses only with an extra argument:

    ```yaml
      - name: s3
        driver: container
        image: ghcr.io/chrislusf/seaweedfs:4.38
        command:
          - mini
          - -ip.bind=0.0.0.0
        ports:
          - 8333
    ```

5. Use the service in the test. `exec` runs a command in the service's pod, and `endpoint` gives the
   URL at which the pytest process reaches a port:

    ```python
    from urllib.request import urlopen


    def test_postgres_answers(services):
        postgres = services["postgres"]

        output = postgres.exec(["psql", "-U", "seanergys", "-d", "seanergys", "-Atc", "SELECT 1"])

        assert output.strip() == "1"


    def test_s3_is_healthy(services):
        with urlopen(services["s3"].endpoint(8333), timeout=5) as response:
            assert response.status == 200
    ```

## Reaching a service from the nodes

The pods of the test reach a container service under its name, on the ports listed in `ports`. A
service called `postgres` is therefore `postgres:5432` for Flux jobs or any other process on the
logical nodes. The name is turned into a DNS label first: it is written in lowercase, and every
character other than a letter, a digit or a hyphen becomes a hyphen, so `seanergys.db` becomes
`seanergys-db`. A service without `ports` is not reachable from other pods.
