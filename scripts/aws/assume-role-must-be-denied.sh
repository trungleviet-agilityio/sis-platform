#!/usr/bin/env bash
# Credit: adapted from ship-it-safely scripts/aws/assert-web-identity-denied.sh (lab ADR 0007 S31, PLAN N1 and N8).
# OIDC negative test, checkpoint step 7 (ADR 0002 O12). It calls STS: run it only from the input-gated `negative`
# job of reusable-oidc-smoke.yml, never in the 4a claims run. The job's token comes from the smoke workflow file,
# which no apply or deploy role trusts (O9), while sub, ref and repository_id match. Each named role must answer
# with an explicit AccessDenied to an unsigned AssumeRoleWithWebIdentity call. A success means the trust is too
# broad; any other error (network, throttling, a malformed request) fails too, because it proves nothing.
# Limit, accepted: STS also answers AccessDenied when the role does not exist or the ARN names another account, so
# a pass here cannot tell a refused trust from a wrong ARN. This test is meaningful only once the same ARN has been
# proven by a successful assume of that role (checkpoint step 8, the dev apply); the step order is the owner's.
# Prints the token's sub and job_workflow_ref, never the token or the account; AWS error text is redacted.
#
# Usage: ACCOUNT=... REGION=... scripts/aws/assume-role-must-be-denied.sh <role name>...

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"
# shellcheck source=scripts/aws/oidc.sh
source "$(dirname "$0")/oidc.sh"

[ $# -ge 1 ] || die "usage: ACCOUNT=... REGION=... scripts/aws/assume-role-must-be-denied.sh <role name>..."
account="${ACCOUNT:-}" region="${REGION:-}"
[ -n "$account" ] || die "ACCOUNT is empty (the AWS_ACCOUNT_ID secret was not passed)"
mask "$account"
[[ "$account" =~ ^[0-9]{12}$ ]] || die "ACCOUNT is not a 12-digit account ID"
[[ "$region" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]] || die "REGION is not a region name"
for role in "$@"; do
  [[ "$role" =~ ^[a-z][a-z0-9-]{1,63}$ ]] || die "role name '$role' is not a <prefix>-<env>-gha-<kind> name"
done
require_cmd aws "the AWS CLI is preinstalled on GitHub-hosted runners"

token="$(oidc_token)"
printf 'claim sub: %s\n' "$(jwt_claim "$token" sub)"
printf 'claim job_workflow_ref: %s\n' "$(jwt_claim "$token" job_workflow_ref)"

err_file="$(mktemp)"
trap 'rm -f "$err_file"' EXIT
for role in "$@"; do
  rc=0
  # No credentials are needed or sent (--no-sign-request). A success would hold credentials: stdout is discarded.
  (
    trap - ERR
    aws sts assume-role-with-web-identity \
      --role-arn "arn:aws:iam::${account}:role/${role}" \
      --role-session-name "gha-oidc-negative-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}" \
      --web-identity-token "$token" --region "$region" --no-sign-request >/dev/null 2>"$err_file"
  ) || rc=$?
  detail="$(redact_ids <"$err_file")"
  [ "$rc" -ne 0 ] || die "${role}: the call succeeded, it must be denied (the trust is too broad)"
  case "$detail" in
    *AccessDenied*) ok "${role}: AccessDenied as designed" ;;
    *) die "${role}: failed for a reason other than AccessDenied (exit ${rc}): ${detail}" ;;
  esac
done
