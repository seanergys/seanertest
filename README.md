# seanertest fixture prototype

This is the minimal pytest + `fixture.yaml` + Docker implementation.

Each test lives in its own directory. The pytest `services` fixture finds the
`fixture.yaml` beside the test file, starts the declared service containers,
waits for published TCP ports to accept connections, yields a mapping of
service names to running service handles, and tears everything down afterwards.

```text
tests/
└── alpha/
    ├── fixture.yaml
    ├── c.yml
    └── test_alpha.py
```

A fixture looks like this:

```yaml
version: 1
services:
  - name: alpha
    image: python:3.12-alpine
    config: c.yml
    ports:
      - 8080
```

`config` is resolved relative to the test directory. It is copied into the
container at `/tmp/seanertest/config.yml` and the service receives
`SEANERTEST_CONFIG=/tmp/seanertest/config.yml`.

The file is copied through the Docker API rather than bind-mounted. This is
important for GitLab DinD, where the pytest job filesystem is not the Docker
daemon filesystem.

Services are attached to a private Docker network. Their fixture `name` is also
a network alias, so services can address each other by names such as `alpha`.
Published ports are assigned random host ports. Tests should use:

```python
alpha = services["alpha"]
url = alpha.endpoint(8080)
```

With DinD, `endpoint()` automatically uses the hostname from `DOCKER_HOST`
(`docker` in the included GitLab job); with a local Unix Docker socket it uses
`127.0.0.1`.

If GitLab registry variables are present, the fixture logs the Docker client in
to `CI_REGISTRY` before pulling images, so private project/group images can be
used directly in `fixture.yaml`.
