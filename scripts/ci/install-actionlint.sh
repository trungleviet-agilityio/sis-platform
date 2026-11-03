#!/usr/bin/env bash
# Install actionlint on a Linux x86_64 CI runner, verified against a SHA-256 pinned here (copied from the
# release's checksums file). Keep ACTIONLINT_VERSION in step with mise.toml. Locally, use `mise install`.
#
# Usage: scripts/ci/install-actionlint.sh <install dir>   (the dir is created; add it to PATH afterwards)

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

ACTIONLINT_VERSION="1.7.12"
ACTIONLINT_SHA256="8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"

[ $# -eq 1 ] || die "usage: scripts/ci/install-actionlint.sh <install dir>"
dest="$1"
[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || die "this installer only supports Linux x86_64; use mise locally"
require_cmd curl "install curl"
require_cmd sha256sum "install coreutils"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
file="actionlint_${ACTIONLINT_VERSION}_linux_amd64.tar.gz"
curl -fsSL --retry 3 -o "$tmp/$file" \
  "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/${file}"
echo "${ACTIONLINT_SHA256}  $tmp/$file" | sha256sum --check --status || die "actionlint checksum mismatch"
mkdir -p "$dest"
tar -xzf "$tmp/$file" -C "$dest" actionlint
ok "actionlint ${ACTIONLINT_VERSION} installed in $dest"
