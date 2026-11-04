#!/usr/bin/env bash
# OIDC claims smoke, checkpoint step 4a (ADR 0002 O12, F3, F19). Makes no AWS call. Requests the job's OIDC token
# for the STS audience and prints the non-secret claims named as arguments (never the token), plus job.workflow_sha.
# Then it fails unless the job_workflow_sha claim, job.workflow_sha and the caller's platform.lock workflow_sha are
# the same commit. The printed job_workflow_ref is the value the apply trust (O9) must match exactly.
#
# Usage: JOB_WORKFLOW_SHA=... LOCK_WORKFLOW_SHA=... \
#          scripts/aws/print-oidc-claims.sh job_workflow_ref job_workflow_sha sub ref repository_id
# Env:   ACTIONS_ID_TOKEN_REQUEST_URL and ACTIONS_ID_TOKEN_REQUEST_TOKEN (set by GitHub with id-token: write)

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"
# shellcheck source=scripts/aws/oidc.sh
source "$(dirname "$0")/oidc.sh"

[ $# -ge 1 ] || die "usage: scripts/aws/print-oidc-claims.sh <claim>..."
job_sha="${JOB_WORKFLOW_SHA:-}" lock_sha="${LOCK_WORKFLOW_SHA:-}"
[[ "$job_sha" =~ ^[0-9a-f]{40}$ ]] || die "JOB_WORKFLOW_SHA must be the 40-hex job.workflow_sha"
[[ "$lock_sha" =~ ^[0-9a-f]{40}$ ]] || die "LOCK_WORKFLOW_SHA must be the 40-hex platform.lock workflow_sha"

for claim in "$@"; do
  case "$claim" in
    job_workflow_ref | job_workflow_sha | sub | ref | repository_id | repository | environment | workflow_ref) ;;
    *) die "claim '$claim' is not on the list of non-secret claims this script prints" ;;
  esac
done

token="$(oidc_token)"
for claim in "$@"; do
  printf 'claim %s: %s\n' "$claim" "$(jwt_claim "$token" "$claim" | redact_ids)"
done
printf 'job.workflow_sha: %s\n' "$job_sha"
printf 'platform.lock workflow_sha: %s\n' "$lock_sha"

claim_sha="$(jwt_claim "$token" job_workflow_sha)"
[ -n "$claim_sha" ] || die "the token has no job_workflow_sha claim"
[ "$claim_sha" = "$job_sha" ] || die "job_workflow_sha claim ${claim_sha} differs from job.workflow_sha ${job_sha}"
[ "$job_sha" = "$lock_sha" ] || die "job.workflow_sha ${job_sha} differs from platform.lock workflow_sha ${lock_sha}"
ok "job_workflow_sha = job.workflow_sha = workflow_sha (${job_sha})"
