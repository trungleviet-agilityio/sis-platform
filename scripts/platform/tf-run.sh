#!/usr/bin/env bash
# Run one terraform command for a reusable workflow without printing its raw output (consumer logs are public).
# The output goes to <log dir>/terraform-<label>.log. On success one line is printed; on failure the log is printed
# with every 12-digit run and dddd-dddd-dddd run replaced by <account> (redact_ids in scripts/lib.sh), then the
# script fails. Refuses to run unless TF_CLI_CONFIG_FILE names the platform CLI config (provider installation from
# the hashicorp namespace only, scripts/platform/terraformrc).
#
# Usage: TF_CLI_CONFIG_FILE=... scripts/platform/tf-run.sh <label> <terraform arguments...>
#        The log dir is RUNNER_TEMP, else TMPDIR, else /tmp.

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -ge 2 ] || die "usage: scripts/platform/tf-run.sh <label> <terraform arguments...>"
label="$1"
shift
[[ "$label" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || die "label must be lowercase letters, digits and hyphens"
cfg="${TF_CLI_CONFIG_FILE:-}"
if [ -z "$cfg" ] || [ ! -f "$cfg" ] || ! grep -q '^provider_installation' "$cfg"; then
  die "TF_CLI_CONFIG_FILE must name the platform CLI config (scripts/platform/terraformrc)"
fi
require_cmd terraform "run scripts/platform/install-terraform.sh"

log_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
log_file="${log_dir%/}/terraform-${label}.log"
rc=0
(
  trap - ERR
  terraform "$@"
) >"$log_file" 2>&1 || rc=$?
if [ "$rc" -ne 0 ]; then
  printf -- '--- terraform %s output (account-like runs redacted)\n' "$label" >&2
  redact_ids <"$log_file" >&2
  die "terraform ${label} failed (exit ${rc})"
fi
ok "terraform ${label} succeeded (raw output kept in the runner's temp dir, not printed)"
