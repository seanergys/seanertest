#!/bin/bash
# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Build the Spack environments of seanertest's tests in the approved image and
# push the binaries, the bootstrapped compiler included, to the seanerstack
# build cache in the SEANERGYS registry.
#
# Usage: scripts/build-buildcache.sh [FIXTURE...]
#
# Without arguments, every fixture under tests/ is built. Before running it:
#
#   docker login registry.seanergys.fz-juelich.de
#
# The login needs write access to the registry. The script needs Docker, uv,
# and checkouts of seanerops and seanerstack. By default they are expected next
# to this checkout, as in software/<project>/<branch>; set SEANEROPS_SRC and
# SEANERSTACK_SRC to use other ones.
#
# Environment variables:
#   BUILDCACHE_URL        Cache to push to
#                         (default: the seanerstack build cache in the registry).
#   SEANERTEST_CACHE_DIR  Keeps downloaded sources and lock files between runs
#                         (default: ~/.cache/seanertest).
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
branch=$(basename "$repo")
seanerops_src=${SEANEROPS_SRC:-$repo/../../seanerops/$branch}
seanerstack_src=${SEANERSTACK_SRC:-$repo/../../seanerstack/$branch}
buildcache_url=${BUILDCACHE_URL:-oci://registry.seanergys.fz-juelich.de/software/seanerstack/buildcache}
cache_dir=${SEANERTEST_CACHE_DIR:-$HOME/.cache/seanertest}
venv=$cache_dir/build-venv

for source in "$seanerops_src" "$seanerstack_src"; do
    if [ ! -f "$source/pyproject.toml" ]; then
        echo "error: no checkout at $source; set SEANEROPS_SRC or SEANERSTACK_SRC" >&2
        exit 1
    fi
done
docker info >/dev/null 2>&1 || { echo "error: Docker is not usable by $(id -un)" >&2; exit 1; }

if [ "$#" -eq 0 ]; then
    set -- "$repo"/tests/*/fixture.yaml
fi

# The same seanerstack checkout is used on the host and in the build container,
# so that both pin the same spack-packages commit.
mkdir -p "$cache_dir"
uv venv --quiet --allow-existing "$venv"
uv pip install --quiet --python "$venv/bin/python" --no-sources \
    -e "$seanerops_src" -e "$seanerstack_src" -e "$repo"

echo "==> building for $buildcache_url"
"$venv/bin/python" -m seanertest.build \
    --push "$buildcache_url" \
    --cache-dir "$cache_dir" \
    --seanerstack-src "$seanerstack_src" \
    "$@"
