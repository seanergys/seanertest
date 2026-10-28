#!/bin/bash
# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Build the compiler of config.yml (gcc@15), which takes hours, in the approved
# image and push it with everything it needs to the seanerstack build cache in
# the SEANERGYS registry. Test sessions then install the compiler from there
# and build the much smaller environments themselves.
#
# Usage: build-compiler.sh
#
# Before running it:
#
#   docker login registry.seanergys.fz-juelich.de
#
# The login needs write access to the registry. The script needs Docker, uv
# and Git. It runs either from a seanertest checkout, or copied anywhere on its
# own; then it clones seanertest and seanerstack from GitLab.
#
# Environment variables:
#   SEANERTEST_SRC        seanertest checkout to use instead of the surrounding
#                         one or a clone.
#   SEANERSTACK_SRC       seanerstack checkout to use instead of the one next to
#                         seanertest or a clone. It must pin the same
#                         spack-packages commit as the seanerstack that test
#                         sessions use, which the build checks.
#   SEANERTEST_REF        Branch of seanertest to clone (default: main).
#   SEANERSTACK_REF       Branch of seanerstack to clone (default: main).
#   BUILDCACHE_URL        Cache to push to
#                         (default: the seanerstack build cache in the registry).
#   SEANERTEST_CACHE_DIR  Keeps clones, the Python environment and downloaded
#                         sources between runs (default: ~/.cache/seanertest).
set -euo pipefail

gitlab=https://gitlab.seanergys.fz-juelich.de/software
buildcache_url=${BUILDCACHE_URL:-oci://registry.seanergys.fz-juelich.de/software/seanerstack/buildcache}
cache_dir=${SEANERTEST_CACHE_DIR:-$HOME/.cache/seanertest}
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Clone or update a branch into a directory below the cache directory.
checkout() {
    local url=$1 ref=$2 directory=$3
    if [ -d "$directory/.git" ]; then
        git -C "$directory" fetch --quiet --depth 1 origin "$ref"
        git -C "$directory" checkout --quiet --detach FETCH_HEAD
    else
        git clone --quiet --depth 1 --branch "$ref" "$url" "$directory"
    fi
    echo "==> $(basename "$directory") $ref at $(git -C "$directory" rev-parse --short HEAD)" >&2
}

mkdir -p "$cache_dir/sources"

if [ -n "${SEANERTEST_SRC:-}" ]; then
    seanertest_src=$SEANERTEST_SRC
elif [ -f "$script_dir/../config.yml" ] && [ -d "$script_dir/../src/seanertest" ]; then
    seanertest_src=$(cd "$script_dir/.." && pwd)
else
    seanertest_src=$cache_dir/sources/seanertest
    checkout "$gitlab/seanertest.git" "${SEANERTEST_REF:-main}" "$seanertest_src"
fi

sibling=$seanertest_src/../../seanerstack/$(basename "$seanertest_src")
if [ -n "${SEANERSTACK_SRC:-}" ]; then
    seanerstack_src=$SEANERSTACK_SRC
elif [ -f "$sibling/pyproject.toml" ]; then
    seanerstack_src=$(cd "$sibling" && pwd)
else
    seanerstack_src=$cache_dir/sources/seanerstack
    checkout "$gitlab/seanerstack.git" "${SEANERSTACK_REF:-main}" "$seanerstack_src"
fi

for source in "$seanertest_src/config.yml" "$seanerstack_src/pyproject.toml"; do
    [ -f "$source" ] || { echo "error: missing $source" >&2; exit 1; }
done
if [ ! -f "$seanertest_src/src/seanertest/build/__main__.py" ]; then
    echo "error: $seanertest_src has no compiler build; use a branch that has it with SEANERTEST_REF" >&2
    exit 1
fi
docker info >/dev/null 2>&1 || { echo "error: Docker is not usable by $(id -un)" >&2; exit 1; }

# Only what the compiler build needs: seanertest itself without its test
# dependencies, the same seanerstack that goes into the build container, and
# the Docker client. seanerstack needs Python 3.12, which uv downloads if the
# machine does not have it.
venv=$cache_dir/compiler-venv
rm -rf "$venv"
uv venv --quiet --python 3.12 "$venv"
uv pip install --quiet --python "$venv/bin/python" --no-sources -e "$seanerstack_src"
uv pip install --quiet --python "$venv/bin/python" --no-deps -e "$seanertest_src"
uv pip install --quiet --python "$venv/bin/python" "docker>=7.1" "PyYAML>=6.0"

echo "==> building the compiler for $buildcache_url"
"$venv/bin/python" -m seanertest.build \
    --compiler-only \
    --config "$seanertest_src/config.yml" \
    --push "$buildcache_url" \
    --cache-dir "$cache_dir" \
    --seanerstack-src "$seanerstack_src"
