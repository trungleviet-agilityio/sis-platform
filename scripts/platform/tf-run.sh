#!/usr/bin/env bash
# Run one terraform command for a reusable workflow without printing its raw output (consumer logs are public).
# The output goes to <log dir>/terraform-<label>.log. With --out FILE, stdout goes to FILE instead (for
# `terraform show -json`) and only stderr goes to the log. On success one line is printed; on failure the log is
# printed with every 12-digit run and dddd-dddd-dddd run replaced by <account> (redact_ids in scripts/lib.sh), then
# the script fails. Refuses to run unless TF_CLI_CONFIG_FILE names the platform CLI config (provider installation
# from the hashicorp namespace only, scripts/platform/terraformrc).
#
# Usage: TF_CLI_CONFIG_FILE=... scripts/platform/tf-run.sh <label> [--out FILE] <terraform arguments...>
#        The log dir is RUNNER_TEMP, else TMPDIR, else /tmp.

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

usage="usage: scripts/platform/tf-run.sh <label> [--out FILE] <terraform arguments...>"
[ $# -ge 2 ] || die "$usage"
label="$1"
shift
out_file=""
if [ "$1" = "--out" ]; then
  if [ $# -lt 3 ] || [ -z "$2" ]; then
    die "$usage"
  fi
  out_file="$2"
  shift 2
fi
[[ "$label" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || die "label must be lowercase letters, digits and hyphens"
cfg="${TF_CLI_CONFIG_FILE:-}"
if [ -z "$cfg" ] || [ ! -f "$cfg" ] || ! grep -q '^provider_installation' "$cfg"; then
  die "TF_CLI_CONFIG_FILE must name the platform CLI config (scripts/platform/terraformrc)"
fi
require_cmd terraform "run scripts/platform/install-terraform.sh"

log_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
log_file="${log_dir%/}/terraform-${label}.log"
rc=0
if [ -n "$out_file" ]; then
  (
    trap - ERR
    terraform "$@"
  ) >"$out_file" 2>"$log_file" || rc=$?
else
  (
    trap - ERR
    terraform "$@"
  ) >"$log_file" 2>&1 || rc=$?
fi
if [ "$rc" -ne 0 ]; then
  printf -- '--- terraform %s output (account-like runs redacted)\n' "$label" >&2
  redact_ids <"$log_file" >&2
  die "terraform ${label} failed (exit ${rc})"
fi
ok "terraform ${label} succeeded (raw output kept in the runner's temp dir, not printed)"
