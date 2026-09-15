#!/bin/sh
set -eu

SPACK=/opt/spack/bin/spack
ENV=/opt/seanertest/env

"$SPACK" -e "$ENV" concretize
"$SPACK" -e "$ENV" install

mkdir -p /tmp/seanertest
"$SPACK" env activate --sh "$ENV" > /tmp/seanertest/activate.sh
