#!/bin/sh
set -eu

spack env create --dir /opt/seanertest/env /opt/seanertest/input/spack.yaml
spack -e /opt/seanertest/env concretize
spack -e /opt/seanertest/env install
spack env activate --sh /opt/seanertest/env > /tmp/seanertest/activate.sh
