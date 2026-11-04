#!/usr/bin/env bash
# Credit: adapted from ship-it-safely and ship-it-serverless scripts/aws/assert-no-account-id.sh (lab ADR 0004, E23).
# Filter for public output (ADR 0002 W3): copy stdin to stdout unchanged, unless it holds an AWS account ID. Then it
# prints nothing and exits 1. It refuses the exact value in ACCOUNT (optional, never printed), any standalone run
# of 12 digits and the dddd-dddd-dddd spelling (alphanumeric boundaries, like the no-aws-account-id pre-commit hook,
# so a digit run inside a SHA is not a hit; unlike the hook, no placeholder is exempt). The reusable plan workflow runs it on the plan summary, and again before the sticky comment.
#
# Usage: <command> | [ACCOUNT=...] scripts/aws/assert-no-account-id.sh

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -eq 0 ] || die "usage: <command> | [ACCOUNT=...] scripts/aws/assert-no-account-id.sh"
account_id_re='(^|[^0-9A-Za-z])[0-9]{12}([^0-9A-Za-z]|$)'
dashed_id_re='(^|[^0-9A-Za-z-])[0-9]{4}-[0-9]{4}-[0-9]{4}([^0-9A-Za-z-]|$)'
text="$(cat)"
account="${ACCOUNT:-}"
if [ -n "$account" ] && printf '%s\n' "$text" | grep -qF -- "$account"; then
  die "output contains the account ID; not publishing it"
fi
if printf '%s\n' "$text" | grep -Eq -e "$account_id_re" -e "$dashed_id_re"; then
  die "output contains a 12-digit number or a dddd-dddd-dddd run (possible account ID); not publishing it"
fi
printf '%s\n' "$text"
