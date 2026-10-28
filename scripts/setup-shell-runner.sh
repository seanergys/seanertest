#!/bin/bash
# SPDX-FileCopyrightText: 2026 SEANERGYS Partners <https://seanergys.eu>
#
# SPDX-License-Identifier: MIT

# Prepare a Rocky Linux 10 VM as the GitLab runner tagged `shell`, which runs
# the minikube jobs of seanertest and seanerops.
#
# Usage, as root on the VM: setup-shell-runner.sh
#
# It installs Docker, minikube, kubectl, uv, Git and gitlab-runner, puts the
# gitlab-runner user into the docker group, and opens the port of seanertest's
# build cache server to the minikube network. It can be run again to update
# the tools. Registering the runner with GitLab stays a manual step, because it
# needs a token; the script prints the command at the end.
#
# Environment variables:
#   MINIKUBE_VERSION     Default: v1.39.0
#   KUBECTL_VERSION      Default: v1.37.0, the Kubernetes version of that minikube
#   UV_VERSION           Default: 0.13.6
#   RUNNER_USER          Default: gitlab-runner
#   CACHE_PORT           Port of seanertest's build cache server (default: 18080)
#   MINIKUBE_SUBNET      Network of minikube's Docker driver (default: 192.168.49.0/24)
set -euo pipefail

# The tools go to /usr/local/bin, which sudo's secure_path on Rocky Linux
# leaves out.
export PATH=/usr/local/bin:$PATH

minikube_version=${MINIKUBE_VERSION:-v1.39.0}
kubectl_version=${KUBECTL_VERSION:-v1.37.0}
uv_version=${UV_VERSION:-0.13.6}
runner_user=${RUNNER_USER:-gitlab-runner}
cache_port=${CACHE_PORT:-18080}
minikube_subnet=${MINIKUBE_SUBNET:-192.168.49.0/24}

if [ "$(id -u)" -ne 0 ]; then
    echo "error: run this script as root" >&2
    exit 1
fi
. /etc/os-release
if [ "${ID:-}" != "rocky" ] || [ "${VERSION_ID%%.*}" != "10" ]; then
    echo "warning: written for Rocky Linux 10, found ${PRETTY_NAME:-unknown}" >&2
fi
if [ "$(uname -m)" != "x86_64" ]; then
    echo "error: only x86_64 is supported" >&2
    exit 1
fi

step() { echo "==> $*"; }

step "Installing base packages"
dnf install -y --setopt=install_weak_deps=False git curl tar gzip ca-certificates dnf-plugins-core

step "Installing Docker from Docker's repository"
dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
systemctl enable --now docker

step "Installing minikube $minikube_version"
curl -fsSL -o /tmp/minikube "https://github.com/kubernetes/minikube/releases/download/$minikube_version/minikube-linux-amd64"
install -m 0755 /tmp/minikube /usr/local/bin/minikube
rm -f /tmp/minikube

step "Installing kubectl $kubectl_version"
curl -fsSL -o /tmp/kubectl "https://dl.k8s.io/release/$kubectl_version/bin/linux/amd64/kubectl"
curl -fsSL -o /tmp/kubectl.sha256 "https://dl.k8s.io/release/$kubectl_version/bin/linux/amd64/kubectl.sha256"
echo "$(cat /tmp/kubectl.sha256)  /tmp/kubectl" | sha256sum --check --quiet
install -m 0755 /tmp/kubectl /usr/local/bin/kubectl
rm -f /tmp/kubectl /tmp/kubectl.sha256

step "Installing uv $uv_version"
archive=uv-x86_64-unknown-linux-gnu.tar.gz
curl -fsSL -o "/tmp/$archive" "https://github.com/astral-sh/uv/releases/download/$uv_version/$archive"
curl -fsSL -o "/tmp/$archive.sha256" "https://github.com/astral-sh/uv/releases/download/$uv_version/$archive.sha256"
(cd /tmp && sha256sum --check --quiet "$archive.sha256")
tar -xzf "/tmp/$archive" -C /tmp
install -m 0755 /tmp/uv-x86_64-unknown-linux-gnu/uv /tmp/uv-x86_64-unknown-linux-gnu/uvx /usr/local/bin/
rm -rf "/tmp/$archive" "/tmp/$archive.sha256" /tmp/uv-x86_64-unknown-linux-gnu

step "Installing gitlab-runner"
curl -fsSL -o /tmp/gitlab-runner https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-amd64
install -m 0755 /tmp/gitlab-runner /usr/local/bin/gitlab-runner
rm -f /tmp/gitlab-runner
if ! id "$runner_user" >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash --comment "GitLab Runner" "$runner_user"
fi
runner_home=$(getent passwd "$runner_user" | cut -d: -f6)
if [ ! -f /etc/systemd/system/gitlab-runner.service ]; then
    gitlab-runner install --user "$runner_user" --working-directory "$runner_home"
fi
systemctl enable --now gitlab-runner

step "Giving $runner_user access to Docker"
usermod --append --groups docker "$runner_user"

if systemctl is-active --quiet firewalld; then
    step "Allowing the minikube network to reach the build cache port $cache_port"
    rule="rule family=ipv4 source address=$minikube_subnet port port=$cache_port protocol=tcp accept"
    if ! firewall-cmd --permanent --query-rich-rule="$rule" >/dev/null; then
        firewall-cmd --permanent --add-rich-rule="$rule"
        firewall-cmd --reload
    fi
fi

step "Checking the tools as $runner_user"
su - "$runner_user" -c 'docker version --format "docker {{.Server.Version}}" && minikube version --short && kubectl version --client | head -1 && uv --version && git --version'

cat <<EOF

The runner VM is prepared. Remaining manual steps:

1. Create a runner in GitLab with the tag 'shell' and copy its token, then
   register it here:

       gitlab-runner register --non-interactive \\
           --url https://gitlab.seanergys.fz-juelich.de \\
           --token <token> \\
           --executor shell

2. Optional: let seanertest install the compiler from the registry instead of
   building it, by logging in as the runner user:

       su - $runner_user -c 'docker login registry.seanergys.fz-juelich.de'
EOF
