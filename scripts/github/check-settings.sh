#!/usr/bin/env bash
# Read-only audit of a GitHub repository's settings (ADR 0001 A12, ADR 0002 O13). Only `gh api` GET requests are made
# (see api_get in check_settings.py); secret and variable values are never read, only their names.
# Usage: scripts/github/check-settings.sh <owner>/<repo> [--envs dev,prod]
# Needs: gh (authenticated, Administration read for rulesets) and python3 (3.9 or newer).

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -ge 1 ] || die "usage: scripts/github/check-settings.sh <owner>/<repo> [--envs dev,prod]"
require_cmd gh "https://cli.github.com"
require_cmd python3 "https://www.python.org"
# A failing audit prints its own report and exits 1, so keep the ERR trap out of the way.
rc=0
python3 -I "$ROOT/scripts/github/check_settings.py" "$@" || rc=$?
exit "$rc"
