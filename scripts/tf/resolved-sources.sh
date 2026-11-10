#!/usr/bin/env bash
# Credit: adapted from ship-it-safely scripts/tf/resolved-sources.sh (lab ADR 0007 fix round 2).
# Fail-closed check of what `terraform init` actually resolved (ADR 0002, H9). Text rules can be fooled by escaped
# quotes, heredocs and comments; Terraform cannot be fooled about where code comes from:
#   - every module in <data dir>/modules/modules.json (the root entry, Key "", excluded) is a local path (./ or ../)
#     or the sis-platform repository at a full commit SHA:
#       git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/<name>?ref=<40 hex>
#     and the ref must equal the release_sha given as the third argument (or SIS_RELEASE_SHA), which the
#     caller reads from platform.lock; a tag, a branch, another repository or another SHA is refused, and
#     so is any platform source when no release_sha is given;
#   - a local source (./ or ../) may not pass through a .terraform or .git directory;
#   - every provider in <dir>/.terraform.lock.hcl is registry.terraform.io/hashicorp/*.
# A directory with no modules has no modules.json, which is fine. A missing lock file is not: init writes one.
#
# Usage: scripts/tf/resolved-sources.sh <terraform dir> <TF_DATA_DIR used for init> [release_sha]

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

{ [ $# -eq 2 ] || [ $# -eq 3 ]; } ||
  die "usage: scripts/tf/resolved-sources.sh <terraform dir> <TF_DATA_DIR used for init> [release_sha]"
dir="$1" data_dir="$2" release_sha="${3:-${SIS_RELEASE_SHA:-}}"
if [ -n "$release_sha" ] && ! [[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]; then
  die "release_sha must be 40 lowercase hex characters"
fi
require_cmd jq "brew install jq"

platform_source='^git::https://github\.com/trungleviet-agilityio/sis-platform\.git//modules/[a-z0-9-]+\?ref=([0-9a-f]{40})$'

bad=()

modules="$data_dir/modules/modules.json"
if [ -f "$modules" ]; then
  while IFS= read -r source; do
    case "$source" in
      ./* | ../*)
        case "/$source/" in
          */.terraform/* | */.git/*)
            bad+=("local module source goes through a .terraform or .git directory: $source")
            ;;
        esac
        ;;
      *)
        if ! [[ "$source" =~ $platform_source ]]; then
          bad+=("module source is not local or sis-platform at a commit SHA: $source")
        elif [ -z "$release_sha" ]; then
          bad+=("sis-platform module source needs the release_sha (third argument or SIS_RELEASE_SHA): $source")
        elif [ "${BASH_REMATCH[1]}" != "$release_sha" ]; then
          bad+=("sis-platform module ref ${BASH_REMATCH[1]} is not the release_sha $release_sha")
        fi
        ;;
    esac
  done < <(jq -r '.Modules[] | select(.Key != "") | .Source' "$modules")
fi

lock="$dir/.terraform.lock.hcl"
[ -f "$lock" ] || die "no .terraform.lock.hcl in $dir (run terraform init first)"
while IFS= read -r provider; do
  case "$provider" in
    registry.terraform.io/hashicorp/*) ;;
    *) bad+=("provider is not hashicorp: $provider") ;;
  esac
done < <(sed -nE 's/^provider "([^"]*)".*/\1/p' "$lock")

if [ ${#bad[@]} -gt 0 ]; then
  for b in "${bad[@]}"; do printf '  - %s\n' "$b" >&2; done
  die "${#bad[@]} resolved source violation(s) in ${dir#"$ROOT"/}"
fi
ok "resolved modules are local or sis-platform at a SHA, and providers are hashicorp: ${dir#"$ROOT"/}"
