#!/usr/bin/env bash
# Credit: adapted from ship-it-serverless scripts/tf/plan-summary.sh (lab ADR 0004, E22 and E23).
# Account-free summary of a Terraform plan for the job summary and the PR comment (ADR 0002 W3). Reads
# `terraform show -json <plan>` on stdin and prints markdown: counts and one row per changed resource (action and
# address only, never attribute values). A consumer repo is public, so a standalone 12-digit run (a possible AWS
# account ID) fails the script instead of being printed. Pipe the result through scripts/aws/assert-no-account-id.sh
# too, which also checks the exact account.
#
# Usage: terraform show -json tfplan | scripts/platform/plan-summary.sh --title <heading text>

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

require_cmd jq "apt-get install jq"
usage="usage: terraform show -json tfplan | scripts/platform/plan-summary.sh --title <heading text>"
{ [ $# -eq 2 ] && [ "$1" = "--title" ] && [ -n "$2" ]; } || die "$usage"
title="$2"
max_rows=200
account_id_re='(^|[^0-9A-Za-z])[0-9]{12}([^0-9A-Za-z]|$)'

input="$(cat)"
[ -n "$input" ] || die "no plan JSON on stdin"
printf '%s' "$input" | jq -e 'type == "object" and has("format_version")' >/dev/null 2>&1 ||
  die "stdin is not the JSON of terraform show -json"

# shellcheck disable=SC2016  # jq program, not shell
program='
  def act:
    if (.change.actions | index("delete")) and (.change.actions | index("create")) then "REPLACE"
    elif .change.actions == ["delete"] then "DELETE"
    elif .change.actions == ["create"] then "create"
    elif .change.actions == ["update"] then "update"
    else (.change.actions | join("+")) end;
  [(.resource_changes // [])[] | select(.change.actions != ["no-op"] and .change.actions != ["read"])] as $c
  | ($c | map(act)) as $l
  | "### \($title)",
    "",
    "**Add \($l | map(select(. == "create")) | length), change \($l | map(select(. == "update")) | length), destroy \($l | map(select(. == "DELETE")) | length), replace \($l | map(select(. == "REPLACE")) | length).**",
    "",
    (if ($c | length) == 0 then "No resource changes."
     else
       "| Action | Address |",
       "|---|---|",
       ($c[:$max][] | "| \(act) | `\(.address)` |"),
       (if ($c | length) > $max then "", "Showing the first \($max) of \($c | length) changes." else empty end)
     end)
'
summary="$(printf '%s' "$input" | jq -r --argjson max "$max_rows" --arg title "$title" "$program")"

if printf '%s\n' "$summary" | grep -Eq "$account_id_re"; then
  die "plan summary contains a 12-digit number (possible account ID); not printing it"
fi
printf '%s\n' "$summary"
