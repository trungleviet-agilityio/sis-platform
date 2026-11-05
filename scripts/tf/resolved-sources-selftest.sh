#!/usr/bin/env bash
# Self-test for scripts/tf/resolved-sources.sh: each case builds a fake data dir and lock file and asserts the exact
# message or the pass. Offline; no Terraform needed.

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"
require_cmd jq "brew install jq"
# The cases below run failing commands on purpose; the ERR trap from lib.sh would print a line for each.
trap - ERR

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

sha="0123456789abcdef0123456789abcdef01234567"
platform="git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=$sha"
failures=0

# case <name> <expected: ok or a message fragment> <module source or ""> <provider>
run_case() {
  local name="$1" expect="$2" source="$3" provider="$4" dir out status
  dir="$tmp/$name"
  mkdir -p "$dir/data/modules"
  printf 'provider "%s" {\n  version = "6.71.0"\n}\n' "$provider" >"$dir/.terraform.lock.hcl"
  if [ -n "$source" ]; then
    printf '{"Modules":[{"Key":"","Source":"","Dir":"."},{"Key":"m","Source":"%s","Dir":"x"}]}\n' "$source" >"$dir/data/modules/modules.json"
  fi
  status=0
  out="$("$(dirname "$0")/resolved-sources.sh" "$dir" "$dir/data" 2>&1)" || status=$?
  if [ "$expect" = ok ]; then
    if [ "$status" -ne 0 ]; then
      printf 'FAIL %s: expected pass, got: %s\n' "$name" "$out" >&2
      failures=$((failures + 1))
    fi
  elif [ "$status" -eq 0 ] || ! printf '%s' "$out" | grep -qF -- "$expect"; then
    printf 'FAIL %s: expected failure with "%s", got status %s: %s\n' "$name" "$expect" "$status" "$out" >&2
    failures=$((failures + 1))
  fi
}

hc=registry.terraform.io/hashicorp/aws
run_case no-modules ok "" "$hc"
run_case local-relative ok "./inner" "$hc"
run_case local-parent ok "../shared" "$hc"
run_case platform-at-sha ok "$platform" "$hc"
run_case platform-at-tag "module source is not local or sis-platform at a commit SHA" "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=v0.2.0" "$hc"
run_case platform-at-branch "module source is not local or sis-platform at a commit SHA" "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=main" "$hc"
run_case platform-short-sha "module source is not local or sis-platform at a commit SHA" "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=0123456" "$hc"
run_case other-repo "module source is not local or sis-platform at a commit SHA" "git::https://github.com/someone/else.git//modules/account-bootstrap?ref=$sha" "$hc"
run_case registry-module "module source is not local or sis-platform at a commit SHA" "terraform-aws-modules/vpc/aws" "$hc"
run_case third-party-provider "provider is not hashicorp: registry.terraform.io/acme/aws" "" "registry.terraform.io/acme/aws"

# A missing lock file is a failure, not a pass.
mkdir -p "$tmp/nolock/data"
status=0
out="$("$(dirname "$0")/resolved-sources.sh" "$tmp/nolock" "$tmp/nolock/data" 2>&1)" || status=$?
if [ "$status" -eq 0 ] || ! printf '%s' "$out" | grep -qF "no .terraform.lock.hcl"; then
  printf 'FAIL nolock: expected "no .terraform.lock.hcl", got status %s: %s\n' "$status" "$out" >&2
  failures=$((failures + 1))
fi

[ "$failures" -eq 0 ] || die "$failures resolved-sources self-test case(s) failed"
ok "resolved-sources self-test"
