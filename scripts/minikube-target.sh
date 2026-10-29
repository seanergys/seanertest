#!/bin/sh
# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Write a seanertest target for a running minikube profile with the Docker
# driver. The cache address is the host's side of the profile's Docker network.
# PORT is optional; a fixed port lets a host firewall allow exactly that port.
#
# Usage: scripts/minikube-target.sh PROFILE KUBECONFIG [PORT] > target.yml
set -eu

profile=${1:?usage: $0 PROFILE KUBECONFIG [PORT]}
kubeconfig=${2:?usage: $0 PROFILE KUBECONFIG [PORT]}
port=${3:-}
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
if [ -n "$port" ]; then
    echo "  port: $port"
fi
