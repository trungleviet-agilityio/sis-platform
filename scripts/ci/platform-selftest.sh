#!/usr/bin/env bash
# Self-test of the scripts the reusable workflows run from `.platform/` (ADR 0002 W3, O11, O12, T3, AB8). Offline:
# curl, aws and terraform are stubs on PATH, so nothing reaches GitHub or AWS. Run by scripts/ci/selftest.sh
# (`make lint`). It lives outside the closure, with its fixtures in scripts/ci/fixtures/platform/, so editing a test
# never moves workflow_sha. The only account ID used is the documented fake 123456789012 (and 111111111111).
# Usage: scripts/ci/platform-selftest.sh

# SC2016: single-quoted `$...` strings below are stub script text, not expansions.
# shellcheck disable=SC2016
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -eq 0 ] || die "usage: scripts/ci/platform-selftest.sh"
require_cmd jq "brew install jq"
fx="$ROOT/scripts/ci/fixtures/platform"
assert="$ROOT/scripts/aws/assert-no-account-id.sh"
summary="$ROOT/scripts/platform/plan-summary.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fake="123456789012"
sha_a="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
sha_b="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

# run <out var file> <command...>: record the exit code in RC and the combined output in $tmp/out.
run() {
  RC=0
  (
    trap - ERR
    "$@"
  ) >"$tmp/out" 2>&1 || RC=$?
}
# expect_ok <label> <fragment or empty> <command...>
expect_ok() {
  local label="$1" want="$2"
  shift 2
  run "$@"
  [ "$RC" -eq 0 ] || die "platform selftest: ${label} should pass, exit ${RC}: $(cat "$tmp/out")"
  if [ -n "$want" ] && ! grep -qF -- "$want" "$tmp/out"; then
    die "platform selftest: ${label} output lacks '${want}': $(cat "$tmp/out")"
  fi
}
# expect_fail <label> <message fragment> <command...>
expect_fail() {
  local label="$1" want="$2"
  shift 2
  run "$@"
  [ "$RC" -ne 0 ] || die "platform selftest: ${label} should fail but passed"
  grep -qF -- "$want" "$tmp/out" || die "platform selftest: ${label} failed without '${want}': $(cat "$tmp/out")"
}

log "assert-no-account-id.sh"
expect_ok "clean text passes through" "plain text" bash -c 'printf "plain text\n" | "$1"' _ "$assert"
expect_ok "a digit run inside a SHA is not a hit" "a1234567890123b" \
  bash -c 'printf "a1234567890123b\n" | "$1"' _ "$assert"
expect_fail "a standalone 12-digit run" "contains a 12-digit number" \
  bash -c 'printf "arn:aws:iam::%s:role/x\n" "$2" | "$1"' _ "$assert" "$fake"
expect_fail "the exact account" "contains the account ID" \
  bash -c 'printf "id x111111111111x\n" | ACCOUNT=111111111111 "$1"' _ "$assert"
expect_fail "an argument" "usage:" "$assert" extra
run bash -c 'printf "arn:aws:iam::%s:role/x\n" "$2" | "$1"' _ "$assert" "$fake"
if grep -qF "$fake" "$tmp/out"; then die "platform selftest: assert-no-account-id.sh printed the refused text"; fi

log "plan-summary.sh"
expect_ok "mixed plan" "**Add 1, change 1, destroy 1, replace 1.**" bash -c '"$1" --title "Terraform plan (dev)" <"$2"' _ "$summary" "$fx/plan-mixed.json"
grep -qF '| REPLACE | `terraform_data.swap` |' "$tmp/out" || die "platform selftest: plan-summary.sh lacks the REPLACE row"
grep -qF 'terraform_data.same' "$tmp/out" && die "platform selftest: plan-summary.sh lists a no-op"
grep -qF 'data.aws_caller_identity' "$tmp/out" && die "platform selftest: plan-summary.sh lists a read"
grep -qF '### Terraform plan (dev)' "$tmp/out" || die "platform selftest: plan-summary.sh lacks the title"
expect_ok "empty plan" "No resource changes." bash -c '"$1" --title t <"$2"' _ "$summary" "$fx/plan-empty.json"
expect_fail "a 12-digit run in an address" "plan summary contains a 12-digit number" \
  bash -c '"$1" --title t <"$2"' _ "$summary" "$fx/plan-account.json"
expect_fail "not a plan" "is not the JSON of terraform show -json" bash -c 'echo "{}" | "$1" --title t' _ "$summary"
expect_fail "no title" "usage:" bash -c '"$1" <"$2"' _ "$summary" "$fx/plan-empty.json"
# The reusable workflows set `defaults.run.shell: bash` (bash --noprofile --norc -eo pipefail): a failing summary in
# the apply job's pipe into assert-no-account-id.sh must fail the step, as it does here.
expect_fail "a failing summary inside the apply step's pipe" "plan summary contains a 12-digit number" \
  bash --noprofile --norc -eo pipefail -c '"$1" --title t <"$3" | "$2" >>/dev/null; echo step-continued' \
  _ "$summary" "$assert" "$fx/plan-account.json"
grep -qF "step-continued" "$tmp/out" && die "platform selftest: the pipe did not stop the step"

log "plan-policy.py"
policy="$ROOT/scripts/platform/plan-policy.py"
arn="arn:aws:iam::${fake}:policy/exa-dev-workload-boundary"
expect_ok "a plan without IAM policies" "the plan creates or changes no IAM policy" \
  python3 -I "$policy" "$fx/plan-mixed.json" --boundary-arn "$arn"
expect_fail "an Allow * policy" "P01" python3 -I "$policy" "$fx/plan-iam-star.json" --boundary-arn "$arn"
[ "$RC" -eq 1 ] || die "platform selftest: plan-policy.py findings should exit 1, got $RC"
expect_fail "not a plan" "not the JSON of terraform show -json" \
  python3 -I "$policy" "$ROOT/examples/consumer/platform.lock" --boundary-arn "$arn"
[ "$RC" -eq 2 ] || die "platform selftest: plan-policy.py bad input should exit 2, got $RC"
expect_fail "no boundary" "Usage: plan-policy.py" python3 -I "$policy" "$fx/plan-mixed.json"

log "resolve.py"
resolve="$ROOT/scripts/platform/resolve.py"
caller="$tmp/caller"
mkdir -p "$caller"
cp "$ROOT/examples/consumer/platform.yaml" "$caller/platform.yaml"
printf '{"lock_version": 1, "version": "v0.2.0", "release_sha": "%s", "workflow_sha": "%s", "trusted_workflow_shas": ["%s", "%s"]}\n' \
  "$sha_a" "$sha_b" "$sha_b" "$sha_a" >"$caller/platform.lock"
ctx() { # <repository> <file path> <sha> <resolve args...>
  local repo="$1" file="$2" sha="$3"
  shift 3
  JOB_WORKFLOW_REPOSITORY="$repo" JOB_WORKFLOW_FILE_PATH="$file" JOB_WORKFLOW_SHA="$sha" python3 -I "$resolve" "$@"
}
good_repo="trungleviet-agilityio/sis-platform"
good_file=".github/workflows/reusable-terraform-plan.yml"
expect_ok "a trusted SHA and a valid manifest" "plan_role=exa-dev-gha-plan" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --env dev --tfvars "$tmp/platform.tfvars.json" \
  --families lambda
for want in "family=lambda" "region=ap-southeast-1" "prefix=exa" "apply_role=exa-dev-gha-apply" \
  "deploy_role=exa-dev-gha-deploy" "release_sha=$sha_a" "workflow_sha=$sha_b" "job_workflow_sha=$sha_a" "env=dev"; do
  grep -qxF "$want" "$tmp/out" || die "platform selftest: resolve.py output lacks the line '$want'"
done
jq -e '.platform.env == "dev" and .platform.roles.apply == "exa-dev-gha-apply"' "$tmp/platform.tfvars.json" >/dev/null ||
  die "platform selftest: resolve.py --tfvars did not write the M7 env slice"
perm="$(python3 -c 'import os, sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$tmp/platform.tfvars.json")"
[ "$perm" = "0o600" ] || die "platform selftest: the tfvars file is $perm, not owner-only"
expect_ok "trust only" "job_workflow_sha=$sha_a" ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --trust-only
expect_fail "another repository" "not trungleviet-agilityio/sis-platform (O11)" \
  ctx "someone/sis-platform" "$good_file" "$sha_a" --caller "$caller" --trust-only
expect_fail "a non-reusable file" "not .github/workflows/reusable-*.yml (O11)" \
  ctx "$good_repo" ".github/workflows/ci.yml" "$sha_a" --caller "$caller" --trust-only
expect_fail "a SHA outside the trust list" "is not in platform.lock trusted_workflow_shas (O11, L1)" \
  ctx "$good_repo" "$good_file" "cccccccccccccccccccccccccccccccccccccccc" --caller "$caller" --trust-only
expect_fail "a short SHA" "job.workflow_sha is not a 40-hex commit SHA (O11)" \
  ctx "$good_repo" "$good_file" "abc123" --caller "$caller" --trust-only
expect_fail "an env outside the manifest" "env 'qa' is not an env of platform.yaml (M6)" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --env qa
expect_fail "an env name with a newline" "must match" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --env "$(printf 'dev\nfamily=x')"
expect_fail "no mode" "Usage:" ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller"
expect_fail "families with trust only" "Usage:" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --trust-only --families lambda
expect_fail "a malformed family list" "Usage:" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --env dev --families 'lambda,Bad;x'
# W2: a valid manifest of a family with no job in the workflow (the ecs example) must fail, not skip to green.
ecs_caller="$tmp/ecs-caller"
mkdir -p "$ecs_caller"
cp "$ROOT/intake/examples/valid/ship-it-safely.yaml" "$ecs_caller/platform.yaml"
cp "$caller/platform.lock" "$ecs_caller/platform.lock"
expect_ok "an ecs manifest without a family list" "family=ecs" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$ecs_caller" --env dev
expect_fail "an ecs manifest in a lambda-only workflow" \
  "runtime family 'ecs' has no job in this workflow (supported: lambda)" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$ecs_caller" --env dev --families lambda
grep -q "^family=" "$tmp/out" && die "platform selftest: resolve.py printed outputs for an unsupported family"
sed 's/^  prod:$/  prod-x:/' "$caller/platform.yaml" >"$tmp/bad.yaml"
cp "$tmp/bad.yaml" "$caller/platform.yaml"
expect_fail "an invalid manifest" "platform.yaml is not valid under --context lint (M8)" \
  ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --env dev
printf '{"lock_version": 1}\n' >"$caller/platform.lock"
expect_fail "a bad lock" "platform.lock" ctx "$good_repo" "$good_file" "$sha_a" --caller "$caller" --trust-only

log "OIDC scripts with stub curl and aws"
bin="$tmp/bin"
mkdir -p "$bin"
b64url() { printf '%s' "$1" | base64 | tr -d '=\n' | tr '/+' '_-'; }
make_token() { # <job_workflow_sha claim>
  local payload
  payload="$(printf '{"sub":"repo:o@1/r@2:environment:dev","ref":"refs/heads/main","repository_id":"2","job_workflow_ref":"trungleviet-agilityio/sis-platform/.github/workflows/reusable-oidc-smoke.yml@%s","job_workflow_sha":"%s"}' "$1" "$1")"
  printf '%s.%s.sig' "$(b64url '{"alg":"RS256"}')" "$(b64url "$payload")"
}
write_curl() { # <token>
  printf '#!/usr/bin/env bash\nprintf %s\n' "'{\"value\":\"$1\"}'" >"$bin/curl"
  chmod +x "$bin/curl"
}
claims="$ROOT/scripts/aws/print-oidc-claims.sh"
oidc_env() {
  PATH="$bin:$PATH" ACTIONS_ID_TOKEN_REQUEST_URL="https://token.invalid/x?a=1" ACTIONS_ID_TOKEN_REQUEST_TOKEN="t" "$@"
}
write_curl "$(make_token "$sha_a")"
expect_ok "claims with equal SHAs" "job_workflow_sha = job.workflow_sha = workflow_sha" \
  oidc_env env JOB_WORKFLOW_SHA="$sha_a" LOCK_WORKFLOW_SHA="$sha_a" "$claims" job_workflow_ref job_workflow_sha sub ref repository_id
grep -qF "claim job_workflow_ref: trungleviet-agilityio/sis-platform/.github/workflows/reusable-oidc-smoke.yml@$sha_a" "$tmp/out" ||
  die "platform selftest: print-oidc-claims.sh did not print job_workflow_ref"
grep -qF ".sig" "$tmp/out" && die "platform selftest: print-oidc-claims.sh printed the token"
expect_fail "claims with a lock SHA that differs" "differs from platform.lock workflow_sha" \
  oidc_env env JOB_WORKFLOW_SHA="$sha_a" LOCK_WORKFLOW_SHA="$sha_b" "$claims" sub
expect_fail "a claim that differs from job.workflow_sha" "job_workflow_sha claim $sha_a differs from job.workflow_sha $sha_b" \
  oidc_env env JOB_WORKFLOW_SHA="$sha_b" LOCK_WORKFLOW_SHA="$sha_b" "$claims" sub
expect_fail "a claim off the list" "is not on the list of non-secret claims" \
  oidc_env env JOB_WORKFLOW_SHA="$sha_a" LOCK_WORKFLOW_SHA="$sha_a" "$claims" sub aud
expect_fail "no token variables" "no OIDC token request variables" \
  env -u ACTIONS_ID_TOKEN_REQUEST_URL JOB_WORKFLOW_SHA="$sha_a" LOCK_WORKFLOW_SHA="$sha_a" PATH="$bin:$PATH" "$claims" sub

denied="$ROOT/scripts/aws/assume-role-must-be-denied.sh"
write_aws() { # <exit code> <stderr text>
  printf '#!/usr/bin/env bash\necho "%s" >&2\nexit %s\n' "$2" "$1" >"$bin/aws"
  chmod +x "$bin/aws"
}
neg_env() { oidc_env env ACCOUNT="$fake" REGION=ap-southeast-1 "$@"; }
write_aws 254 "An error occurred (AccessDenied) when calling the AssumeRoleWithWebIdentity operation: Not authorized for $fake"
expect_ok "AccessDenied from every role" "exa-dev-gha-deploy: AccessDenied as designed" \
  neg_env "$denied" exa-dev-gha-apply exa-dev-gha-deploy
grep -qF "$fake" "$tmp/out" && die "platform selftest: assume-role-must-be-denied.sh printed the account"
write_aws 0 ""
expect_fail "a role that accepts the token" "the call succeeded, it must be denied" neg_env "$denied" exa-dev-gha-apply
write_aws 255 "Could not connect to the endpoint URL"
expect_fail "a network error" "failed for a reason other than AccessDenied" neg_env "$denied" exa-dev-gha-apply
expect_fail "an empty account" "ACCOUNT is empty" \
  oidc_env env ACCOUNT="" REGION=ap-southeast-1 "$denied" exa-dev-gha-apply
expect_fail "a bad role name" "is not a <prefix>-<env>-gha-<kind> name" neg_env "$denied" 'x;y'

log "tf-init.sh with a stub terraform"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >>"%s/tf-args"\n' "$tmp" >"$bin/terraform"
chmod +x "$bin/terraform"
work="$tmp/work"
mkdir -p "$work/infra/envs/dev"
init_env() {
  (cd "$work" && PATH="$bin:$PATH" ACCOUNT="$fake" ENV_NAME=dev REGION=ap-southeast-1 PREFIX=exa TF_DATA_DIR="$tmp/data" "$@")
}
expect_fail "no lock file" "is not committed" init_env "$ROOT/scripts/platform/tf-init.sh"
touch "$work/infra/envs/dev/.terraform.lock.hcl"
expect_ok "composed backend" "initialized infra/envs/dev" init_env "$ROOT/scripts/platform/tf-init.sh"
grep -qF "bucket=exa-dev-tfstate-${fake}-ap-southeast-1-an" "$tmp/tf-args" || die "platform selftest: tf-init.sh bucket is wrong"
grep -qF "key=envs/dev/terraform.tfstate" "$tmp/tf-args" || die "platform selftest: tf-init.sh key is wrong"
grep -qF -- "-lockfile=readonly" "$tmp/tf-args" || die "platform selftest: tf-init.sh does not init with -lockfile=readonly"
grep -qF "use_path_style=true" "$tmp/tf-args" || die "platform selftest: tf-init.sh does not use path style"
grep -qF "$fake" "$tmp/out" && die "platform selftest: tf-init.sh printed the account"
expect_fail "an empty account" "ACCOUNT is empty" init_env env ACCOUNT= "$ROOT/scripts/platform/tf-init.sh"
expect_fail "a bad env" "ENV_NAME must match" init_env env ENV_NAME=Dev "$ROOT/scripts/platform/tf-init.sh"

log "pins kept in step"
inst="$ROOT/scripts/platform/install-terraform.sh"
ci_inst="$ROOT/scripts/ci/install-tf-tools.sh"
for var in TERRAFORM_VERSION TERRAFORM_SHA256; do
  a="$(sed -n "s/^${var}=\"\(.*\)\"\$/\1/p" "$inst")"
  b="$(sed -n "s/^${var}=\"\(.*\)\"\$/\1/p" "$ci_inst")"
  [ -n "$a" ] && [ "$a" = "$b" ] || die "platform selftest: ${var} differs between install-terraform.sh and install-tf-tools.sh"
done
grep -v '^ *#' "$ROOT/scripts/platform/requirements.txt" >"$tmp/req-a"
grep -v '^ *#' "$ROOT/scripts/ci/requirements-test.txt" >"$tmp/req-b"
cmp -s "$tmp/req-a" "$tmp/req-b" ||
  die "platform selftest: scripts/platform/requirements.txt pins differ from scripts/ci/requirements-test.txt"

ok "platform script self-tests pass"
