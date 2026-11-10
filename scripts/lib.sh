# shellcheck shell=bash disable=SC2034  # the variables are read by the scripts that source this file
# Shared helpers for scripts/**/*.sh. Source it; do not run it.
# Written for the bash 3.2 that ships with macOS: no mapfile, no associative arrays.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ROOT

# Colors only on a terminal, so CI logs stay plain (https://no-color.org).
if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then
  _blue=$'\033[34m' _green=$'\033[32m' _red=$'\033[31m' _reset=$'\033[0m'
else
  _blue='' _green='' _red='' _reset=''
fi

# All output goes to stderr, so a script's stdout stays free for data.
log() { printf '%s==>%s %s\n' "$_blue" "$_reset" "$*" >&2; }
ok() { printf '%sok%s  %s\n' "$_green" "$_reset" "$*" >&2; }
die() {
  if [ -n "${GITHUB_ACTIONS:-}" ]; then
    printf '::error::%s\n' "$*" >&2
  else
    printf '%serror%s %s\n' "$_red" "$_reset" "$*" >&2
  fi
  exit 1
}

trap 'die "${BASH_SOURCE[1]##*/}: command failed at line $LINENO"' ERR

# mask <value>: hide a value in every later log line of a GitHub job (a workflow command on stdout). Prints nothing
# outside GitHub Actions, so a local run or a self-test never carries the value.
mask() {
  if [ -n "${GITHUB_ACTIONS:-}" ]; then printf '::add-mask::%s\n' "$1"; fi
}

# redact_ids: filter that replaces every run of 12 digits, and the dddd-dddd-dddd spelling, with <account>, so
# AWS and Terraform output can be printed in a public log. It over-redacts on purpose (any 12-digit run).
redact_ids() { sed -E -e 's/[0-9]{4}-[0-9]{4}-[0-9]{4}/<account>/g' -e 's/[0-9]{12}/<account>/g'; }

# require_cmd <command> <install hint>
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$1 not found. Install: $2"
}
