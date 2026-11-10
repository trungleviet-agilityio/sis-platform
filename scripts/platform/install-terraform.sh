#!/usr/bin/env bash
# Install terraform on a Linux x86_64 runner for the reusable workflows (ADR 0002 AB8), verified against the
# SHA-256 pinned here (from https://releases.hashicorp.com/terraform/<v>/terraform_<v>_SHA256SUMS). This file is in
# the workflow closure; scripts/ci/install-tf-tools.sh is the CI copy for module checks. scripts/ci/selftest.sh
# asserts both hold the same version and digest, and that the version matches mise.toml.
#
# Usage: scripts/platform/install-terraform.sh <install dir>   (the dir is created; add it to PATH afterwards)

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

TERRAFORM_VERSION="1.17.1"
TERRAFORM_SHA256="4638628058e71a55212b1c563712eac03b902128f40740f3dc8174df12135061"

[ $# -eq 1 ] || die "usage: scripts/platform/install-terraform.sh <install dir>"
dest="$1"
[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || die "this installer only supports Linux x86_64"
require_cmd curl "install curl"
require_cmd sha256sum "install coreutils"
require_cmd unzip "install unzip"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$dest"
curl -fsSL --retry 3 -o "$tmp/terraform.zip" \
  "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
echo "${TERRAFORM_SHA256}  $tmp/terraform.zip" | sha256sum --check --status || die "terraform checksum mismatch"
unzip -q -o "$tmp/terraform.zip" terraform -d "$dest"
"$dest/terraform" version
ok "terraform ${TERRAFORM_VERSION} installed in $dest"
