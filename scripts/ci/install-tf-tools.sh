#!/usr/bin/env bash
# Install terraform, tflint and terraform-docs on a Linux x86_64 CI runner, each verified against a SHA-256
# pinned here. The values come from each release's own checksums file:
#   terraform       https://releases.hashicorp.com/terraform/<v>/terraform_<v>_SHA256SUMS
#   tflint          https://github.com/terraform-linters/tflint/releases/download/v<v>/checksums.txt
#   terraform-docs  https://github.com/terraform-docs/terraform-docs/releases/download/v<v>/terraform-docs-v<v>.sha256sum
# Keep the three versions in step with mise.toml (scripts/ci/selftest.sh checks it). Locally, use `mise install`.
#
# Usage: scripts/ci/install-tf-tools.sh <install dir>   (the dir is created; add it to PATH afterwards)

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

TERRAFORM_VERSION="1.17.1"
TERRAFORM_SHA256="4638628058e71a55212b1c563712eac03b902128f40740f3dc8174df12135061"
TFLINT_VERSION="0.65.0"
TFLINT_SHA256="d4c545ed2e29d6338604b586f34f544f380f70f243aa72f7b484713835eaec61"
TERRAFORM_DOCS_VERSION="0.24.0"
TERRAFORM_DOCS_SHA256="9005daf969de0b50134493a2c00078b49f5f5b39d021cda7c89bf4d4f3d776d3"

[ $# -eq 1 ] || die "usage: scripts/ci/install-tf-tools.sh <install dir>"
dest="$1"
[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || die "this installer only supports Linux x86_64; use mise locally"
require_cmd curl "install curl"
require_cmd sha256sum "install coreutils"
require_cmd unzip "install unzip"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$dest"

# fetch <name> <url> <sha256>: download into $tmp/<name> and verify
fetch() {
  curl -fsSL --retry 3 -o "$tmp/$1" "$2"
  echo "$3  $tmp/$1" | sha256sum --check --status || die "$1 checksum mismatch"
}

fetch terraform.zip \
  "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
  "$TERRAFORM_SHA256"
unzip -q -o "$tmp/terraform.zip" terraform -d "$dest"

fetch tflint.zip \
  "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_amd64.zip" \
  "$TFLINT_SHA256"
unzip -q -o "$tmp/tflint.zip" tflint -d "$dest"

fetch terraform-docs.tar.gz \
  "https://github.com/terraform-docs/terraform-docs/releases/download/v${TERRAFORM_DOCS_VERSION}/terraform-docs-v${TERRAFORM_DOCS_VERSION}-linux-amd64.tar.gz" \
  "$TERRAFORM_DOCS_SHA256"
tar -xzf "$tmp/terraform-docs.tar.gz" -C "$dest" terraform-docs

ok "terraform ${TERRAFORM_VERSION}, tflint ${TFLINT_VERSION}, terraform-docs ${TERRAFORM_DOCS_VERSION} installed in $dest"
