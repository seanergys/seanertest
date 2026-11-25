<!--
SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>

SPDX-License-Identifier: MIT
-->

# Configuration file

`config.yml` at the repository root holds the settings that apply to every target. Seanertest finds
it by searching upward from the pytest root directory, and `--seanertest-config` selects another
file. Unknown keys are rejected.

```yaml
version: 1

sources:
  spack:
    git: https://github.com/spack/spack.git
  spack_packages:
    git: https://github.com/spack/spack-packages.git
  seanerstack:
    pip: seanerstack

compiler: gcc@15

upstream_caches:
  - url: oci://registry.seanergys.fz-juelich.de/software/seanerstack/buildcache
    push: true

architectures:
  x86_64:
    image: docker.io/rockylinux/rockylinux:10
    target: x86_64_v3

system_packages:
  build: [python3, python3-pip, git, gcc, gcc-c++, gcc-gfortran, make]
  install: [python3, git, tar, gzip]
  node: [hostname, procps-ng]
```

| Key | Meaning |
| --- | --- |
| `version` | The format version. Only `1` is supported. |
| `sources.spack.git` | The location of Spack. The commit is the one that seanerstack pins, and the build container and every pod fetch it. |
| `sources.spack_packages.git` | The location of `spack-packages`. The commit is the one that seanerstack pins. |
| `sources.seanerstack.pip` | The pip requirement for seanerstack in the build container. A plain `seanerstack` means the version installed next to seanertest. |
| `compiler` | The compiler that seanerstack bootstraps and that builds every environment. |
| `upstream_caches` | Build caches that the build container installs binaries from before it builds anything. |
| `architectures.NAME.image` | The approved image of the build container and of every pod. |
| `architectures.NAME.target` | The Spack target that every package is built for. |
| `system_packages.build` | Packages that `dnf` installs in the build container. |
| `system_packages.install` | Packages that `dnf` installs in the installer pods. |
| `system_packages.node` | Packages that `dnf` installs in the pods of the logical nodes. |

## Upstream caches

An entry of `upstream_caches` is either an `oci://` URL or a mapping with the following keys.

| Key | Default | Meaning |
| --- | --- | --- |
| `url` | | The `oci://` URL of the cache. |
| `push` | `false` | After the build, push every binary that the cache is missing to it. A push that fails, for example with credentials that may only read, logs a warning and does not fail the build. |

Credentials come from `SEANERTEST_UPSTREAM_USERNAME` and `SEANERTEST_UPSTREAM_PASSWORD`, or from
`docker login` for the registry. An upstream cache without credentials is left out, and everything
it holds is built from source.

In the build container, the upstream caches are the build caches of seanerstack's configuration.
The first one is the cache of its toolchain, where seanerstack's bootstrap looks for the lockfile of
the compiler. The seanerstack build cache keeps that lockfile, so the build container installs the
compiler that the cache holds instead of building it.
