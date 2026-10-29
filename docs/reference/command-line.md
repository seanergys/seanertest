<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Command line

## pytest options

Seanertest registers itself as a pytest plugin and adds these options to `pytest`.

| Option | Environment variable | Meaning |
| --- | --- | --- |
| `--target NAME` | `SEANERTEST_TARGET` | A target file, or a name that refers to `targets/NAME.yml`. Without a target, seanertest does nothing, and tests that use `services` fail. |
| `--cache-dir DIR` | `SEANERTEST_CACHE_DIR` | Keeps the build cache, the lock files and the downloaded sources between runs. Without it, a temporary directory is used. |
| `--seanertest-config FILE` | | The configuration file. By default, `config.yml` is found upward from the pytest root directory. |

| Exit status | Meaning |
| --- | --- |
| 0, 1, 2, 4, 5 | As defined by pytest. |
| 3 | The build phase failed, and no test ran. |

## python -m seanertest.build

Runs the build phase on its own, with the same image, Spack, recipes, compiler and target as a test
session.

```bash
python -m seanertest.build [OPTIONS] FIXTURE...
python -m seanertest.build [OPTIONS] --compiler-only
```

| Option | Meaning |
| --- | --- |
| `FIXTURE...` | The `fixture.yaml` files whose Spack environments are built. |
| `--compiler-only` | Builds only the compiler of `config.yml` and no environments. |
| `--push OCI_URL` | Pushes to this `oci://` cache instead of the local cache in the cache directory. |
| `--cache-dir DIR` | The cache directory, by default `~/.cache/seanertest`. |
| `--config FILE` | The configuration file, by default found upward from the first fixture or the current directory. |
| `--architecture NAME` | The architecture of `config.yml`, by default `x86_64`. |
| `--seanerstack-src DIR` | A seanerstack checkout to install in the build container instead of the package. |

## Scripts

| Script | Meaning |
| --- | --- |
| `scripts/minikube-target.sh PROFILE KUBECONFIG [PORT]` | Writes a target for a running minikube profile with the Docker driver to standard output. |
| `scripts/build-compiler.sh` | Builds the compiler and pushes it to the seanerstack build cache. |
| `scripts/setup-shell-runner.sh` | Prepares a Rocky Linux 10 VM as the CI runner. Runs as root. |

## Environment variables

| Variable | Meaning |
| --- | --- |
| `SEANERTEST_TARGET` | The default of `--target`. |
| `SEANERTEST_CACHE_DIR` | The default of `--cache-dir`. |
| `SEANERTEST_SEANERSTACK_SRC` | A seanerstack checkout that the build container installs instead of the package. |
| `SEANERTEST_OCI_USERNAME`, `SEANERTEST_OCI_PASSWORD` | Credentials for the OCI cache of a target. They take precedence over `docker login`. |
| `SEANERTEST_UPSTREAM_USERNAME`, `SEANERTEST_UPSTREAM_PASSWORD` | Credentials for the upstream caches of `config.yml`. They take precedence over `docker login`. |
| `SEANERTEST_GIT_TOKEN`, `SEANERTEST_GIT_USERNAME` | A token, and its user name, by default `oauth2`, for installing seanerstack from a Git URL in the build container. |
| `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL` | Passed into the build container, where pip installs seanerstack. |
| `DOCKER_CONFIG` | The directory of Docker's `config.json`, by default `~/.docker`. |
