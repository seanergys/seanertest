#!/bin/sh
# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Write a seanertest target for a running minikube profile with the Docker
# driver. The cache address is the host's side of the profile's Docker network.
#
# Usage: scripts/minikube-target.sh PROFILE KUBECONFIG > target.yml
set -eu

profile=${1:?usage: $0 PROFILE KUBECONFIG}
kubeconfig=${2:?usage: $0 PROFILE KUBECONFIG}
address=$(docker network inspect "$profile" --format '{{(index .IPAM.Config 0).Gateway}}')

cat <<TARGET
version: 1
name: $profile
architecture: x86_64
runtime:
  type: external
  kubeconfig: $kubeconfig
nodes:
  - $profile
cache:
  type: http
  address: $address
TARGET
