#!/bin/bash
# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Build the compiler of config.yml (gcc@15), which takes hours, in the approved
# image and push it with everything it needs to the seanerstack build cache in
# the SEANERGYS registry. Test sessions then install the compiler from there
# and build the much smaller environments themselves.
#
# Usage: scripts/build-compiler.sh
#
# Before running it:
#
#   docker login registry.seanergys.fz-juelich.de
#
# The login needs write access to the registry. The script needs Docker, uv
# and a checkout of seanerstack. By default the checkout is expected next to
# this one, as in software/<project>/<branch>; set SEANERSTACK_SRC to use
# another one. It must pin the same spack-packages commit as the seanerstack
# that test sessions use, which the build checks.
#
# Environment variables:
#   BUILDCACHE_URL        Cache to push to
#                         (default: the seanerstack build cache in the registry).
#   SEANERTEST_CACHE_DIR  Keeps downloaded sources between runs
#                         (default: ~/.cache/seanertest).
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
seanerstack_src=${SEANERSTACK_SRC:-$repo/../../seanerstack/$(basename "$repo")}
buildcache_url=${BUILDCACHE_URL:-oci://registry.seanergys.fz-juelich.de/software/seanerstack/buildcache}
cache_dir=${SEANERTEST_CACHE_DIR:-$HOME/.cache/seanertest}
venv=$cache_dir/compiler-venv

if [ ! -f "$seanerstack_src/pyproject.toml" ]; then
    echo "error: no seanerstack checkout at $seanerstack_src; set SEANERSTACK_SRC" >&2
    exit 1
fi
docker info >/dev/null 2>&1 || { echo "error: Docker is not usable by $(id -un)" >&2; exit 1; }

# Only what the compiler build needs: seanertest itself without its test
# dependencies, the same seanerstack checkout that goes into the build
# container, and the Docker client.
mkdir -p "$cache_dir"
uv venv --quiet --allow-existing "$venv"
uv pip install --quiet --python "$venv/bin/python" --no-sources -e "$seanerstack_src"
uv pip install --quiet --python "$venv/bin/python" --no-deps -e "$repo"
uv pip install --quiet --python "$venv/bin/python" "docker>=7.1" "PyYAML>=6.0"

echo "==> building the compiler for $buildcache_url"
"$venv/bin/python" -m seanertest.build \
    --compiler-only \
    --config "$repo/config.yml" \
    --push "$buildcache_url" \
    --cache-dir "$cache_dir" \
    --seanerstack-src "$seanerstack_src"
