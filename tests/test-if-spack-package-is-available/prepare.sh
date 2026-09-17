#!/bin/sh

# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Prepare the small package environment used by this behavior test.
set -eux

SPACK=/opt/spack/bin/spack
ENV=/opt/seanertest/env

# Keep this smoke test deliberately small.  CI runners may expose many CPUs
# while having a comparatively small memory limit.
"$SPACK" -e "$ENV" concretize -j 1
"$SPACK" -e "$ENV" install -j 1

mkdir -p /tmp/seanertest
"$SPACK" env activate --sh "$ENV" > /tmp/seanertest/activate.sh
