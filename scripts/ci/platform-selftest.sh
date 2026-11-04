#!/usr/bin/env bash
# Self-test of the scripts the reusable workflows run from `.platform/` (ADR 0002 W3, O11, O12, T3, AB8). Offline:
# curl, aws and terraform are stubs on PATH, so nothing reaches GitHub or AWS. Run by scripts/ci/selftest.sh
# (`make lint`). It lives outside the closure, with its fixtures in scripts/ci/fixtures/platform/, so editing a test
# never moves workflow_sha. The only account IDs used are the documented fakes 123456789012 and 111111111111.
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

# run <command...>: record the exit code in RC and the combined output in $tmp/out.
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
# has <label> <fixed string>...: the last output holds every string.
has() {
  local label="$1" s
  shift
  for s in "$@"; do grep -qF -- "$s" "$tmp/out" || die "platform selftest: ${label}: output lacks '${s}'"; done
}
# lacks <label> <fixed string>...: the last output holds none of them.
lacks() {
  local label="$1" s
  shift
  for s in "$@"; do
    if grep -qF -- "$s" "$tmp/out"; then die "platform selftest: ${label}: output holds '${s}'"; fi
  done
}
# piped <text> <command...>: feed text to the command on stdin.
piped() {
  local text="$1"
  shift
  printf '%s\n' "$text" | "$@"
}

log "assert-no-account-id.sh"
expect_ok "clean text passes through" "plain text" piped "plain text" "$assert"
expect_ok "a digit run inside a SHA is not a hit" "a1234567890123b" piped "a1234567890123b" "$assert"
for text in "arn:aws:iam::${fake}:role/x" "account 1234-5678-9012 here" "id:$(printf "%s-%s-%s" 1111 2222 3333)"; do
  expect_fail "account-like run in '${text}'" "possible account ID" piped "$text" "$assert"
  lacks "nothing printed for '${text}'" "$text"
done
expect_ok "a longer dashed number is not a hit" "1234-5678-9012-3456" piped "uuid 1234-5678-9012-3456" "$assert"
expect_fail "the exact account" "contains the account ID" \
  bash -c 'printf "id x111111111111x\n" | ACCOUNT=111111111111 "$1"' _ "$assert"
expect_fail "an argument" "usage:" "$assert" extra

log "plan-summary.sh (piped through assert-no-account-id.sh, as the workflows do)"
expect_ok "mixed plan" "**Add 1, change 1, destroy 1, replace 1.**" \
  bash -c '"$1" --title "Terraform plan (dev)" <"$2"' _ "$summary" "$fx/plan-mixed.json"
has "mixed plan" '| REPLACE | `terraform_data.swap` |' '### Terraform plan (dev)'
lacks "mixed plan" 'terraform_data.same' 'data.aws_caller_identity'
expect_ok "empty plan" "No resource changes." bash -c '"$1" --title t <"$2"' _ "$summary" "$fx/plan-empty.json"
expect_fail "a 12-digit run in an address" "possible account ID" \
  bash -c '"$1" --title t <"$2" | "$3"' _ "$summary" "$fx/plan-account.json" "$assert"
expect_fail "not a plan" "is not the JSON of terraform show -json" piped "{}" "$summary" --title t
expect_fail "no title" "usage:" bash -c '"$1" <"$2"' _ "$summary" "$fx/plan-empty.json"
# The reusable workflows set `defaults.run.shell: bash` (bash --noprofile --norc -eo pipefail): a failing summary in
# the apply step's pipe into assert-no-account-id.sh must fail the step, as it does here.
expect_fail "a failing summary inside the apply step's pipe" "is not the JSON of terraform show -json" \
  bash --noprofile --norc -eo pipefail -c 'echo "{}" | "$1" --title t | "$2" >>/dev/null; echo step-continued' \
  _ "$summary" "$assert"
lacks "the pipe stops the step" "step-continued"

log "policy.py --allow-no-policy on plans"
policy="$ROOT/scripts/tf/policy.py"
arn="arn:aws:iam::${fake}:policy/exa-dev-workload-boundary"
expect_ok "a plan without IAM policies" "the plan creates or changes no IAM policy" \
  python3 -I "$policy" "$fx/plan-mixed.json" --allow-no-policy --boundary-arn "$arn"
expect_ok "a plan with a scoped policy" "policy lint: no findings" \
  python3 -I "$policy" "$fx/plan-iam-ok.json" --allow-no-policy --boundary-arn "$arn"
expect_fail "an Allow * policy" "P01" python3 -I "$policy" "$fx/plan-iam-star.json" --allow-no-policy --boundary-arn "$arn"
[ "$RC" -eq 1 ] || die "platform selftest: policy findings should exit 1, got $RC"
expect_fail "not a plan" "not the JSON of terraform show -json (--allow-no-policy)" \
  python3 -I "$policy" "$ROOT/examples/consumer/platform.lock" --allow-no-policy --boundary-arn "$arn"
[ "$RC" -eq 2 ] || die "platform selftest: policy bad input should exit 2, got $RC"

log "resolve.py"
resolve="$ROOT/scripts/platform/resolve.py"
caller="$tmp/caller"
mkdir -p "$caller"
cp "$ROOT/examples/consumer/platform.yaml" "$caller/platform.yaml"
cp "$ROOT/examples/consumer/project.env" "$caller/project.env"
printf '{"lock_version": 1, "version": "v0.2.0", "release_sha": "%s", "workflow_sha": "%s", "trusted_workflow_shas": ["%s", "%s"]}\n' \
  "$sha_a" "$sha_b" "$sha_b" "$sha_a" >"$caller/platform.lock"
ctx() { # <repository> <file path> <sha> <resolve args...>
  local repo="$1" file="$2" sha="$3"
  shift 3
  JOB_WORKFLOW_REPOSITORY="$repo" JOB_WORKFLOW_FILE_PATH="$file" JOB_WORKFLOW_SHA="$sha" python3 -I "$resolve" "$@"
}
good_repo="trungleviet-agilityio/sis-platform"
good_file=".github/workflows/reusable-terraform-plan.yml"
good() { ctx "$good_repo" "$good_file" "$sha_a" "$@"; }
expect_ok "a trusted SHA and a valid manifest" "plan_role=exa-dev-gha-plan" \
  good --caller "$caller" --env dev --tfvars "$tmp/platform.tfvars.json" --families lambda
for want in "family=lambda" "region=ap-southeast-1" "prefix=exa" "apply_role=exa-dev-gha-apply" \
  "deploy_role=exa-dev-gha-deploy" "release_sha=$sha_a" "workflow_sha=$sha_b" "job_workflow_sha=$sha_a" "env=dev"; do
  grep -qxF "$want" "$tmp/out" || die "platform selftest: resolve.py output lacks the line '$want'"
done
jq -e '.platform.env == "dev" and .platform.roles.apply == "exa-dev-gha-apply"' "$tmp/platform.tfvars.json" >/dev/null ||
  die "platform selftest: resolve.py --tfvars did not write the M7 env slice"
perm="$(python3 -c 'import os, sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$tmp/platform.tfvars.json")"
[ "$perm" = "0o600" ] || die "platform selftest: the tfvars file is $perm, not owner-only"
expect_ok "trust only" "job_workflow_sha=$sha_a" good --caller "$caller" --trust-only
# One row per refusal: label | message | repository | file | sha | arguments (split on spaces)
while IFS='|' read -r label want repo file sha args; do
  # shellcheck disable=SC2086  # the arguments column is split on purpose
  expect_fail "$label" "$want" ctx "$repo" "$file" "$sha" --caller "$caller" $args
done <<EOF
another repository|not trungleviet-agilityio/sis-platform (O11)|someone/sis-platform|$good_file|$sha_a|--trust-only
a non-reusable file|not .github/workflows/reusable-*.yml (O11)|$good_repo|.github/workflows/ci.yml|$sha_a|--trust-only
a SHA outside the trust list|is not in platform.lock trusted_workflow_shas (O11, L1)|$good_repo|$good_file|cccccccccccccccccccccccccccccccccccccccc|--trust-only
a short SHA|job.workflow_sha is not a 40-hex commit SHA (O11)|$good_repo|$good_file|abc123|--trust-only
an env outside the manifest|env 'qa' is not an env of platform.yaml (M6)|$good_repo|$good_file|$sha_a|--env qa
no mode|Usage:|$good_repo|$good_file|$sha_a|
families with trust only|Usage:|$good_repo|$good_file|$sha_a|--trust-only --families lambda
a malformed family list|Usage:|$good_repo|$good_file|$sha_a|--env dev --families lambda,Bad;x
EOF
expect_fail "an env name with a newline" "must match" good --caller "$caller" --env "$(printf 'dev\nfamily=x')"

# M7: project.env must set SIS_PROJECT_PREFIX once, equal to project.prefix.
cp "$caller/project.env" "$tmp/project.env"
printf 'SIS_PROJECT_PREFIX=other\n' >"$caller/project.env"
expect_fail "a project.env prefix that differs" "project.env SIS_PROJECT_PREFIX 'other' differs from platform.yaml project.prefix 'exa' (M7)" \
  good --caller "$caller" --env dev
printf '# no prefix\nSIS_GITHUB_OWNER=o\n' >"$caller/project.env"
expect_fail "a project.env without the key" "project.env must set SIS_PROJECT_PREFIX exactly once (M7)" good --caller "$caller" --env dev
rm "$caller/project.env"
expect_fail "no project.env" "project.env: cannot read" good --caller "$caller" --env dev
cp "$tmp/project.env" "$caller/project.env"

# W2: a valid manifest of a family with no job in the workflow (the ecs example) must fail, not skip to green.
ecs_caller="$tmp/ecs-caller"
mkdir -p "$ecs_caller"
cp "$ROOT/intake/examples/valid/ship-it-safely.yaml" "$ecs_caller/platform.yaml"
cp "$caller/platform.lock" "$ecs_caller/platform.lock"
ecs_prefix="$(python3 -I "$ROOT/intake/sis_intake/validate.py" "$ecs_caller/platform.yaml" --json | jq -r '.project.prefix')"
printf 'SIS_PROJECT_PREFIX=%s\n' "$ecs_prefix" >"$ecs_caller/project.env"
expect_ok "an ecs manifest without a family list" "family=ecs" good --caller "$ecs_caller" --env dev
expect_fail "an ecs manifest in a lambda-only workflow" \
  "runtime family 'ecs' has no job in this workflow (supported: lambda)" \
  good --caller "$ecs_caller" --env dev --families lambda
lacks "no outputs for an unsupported family" "family="

sed 's/^  prod:$/  prod-x:/' "$caller/platform.yaml" >"$tmp/bad.yaml"
cp "$tmp/bad.yaml" "$caller/platform.yaml"
expect_fail "an invalid manifest" "platform.yaml is not valid under --context lint (M8)" good --caller "$caller" --env dev
printf '{"lock_version": 1}\n' >"$caller/platform.lock"
expect_fail "a bad lock" "platform.lock" good --caller "$caller" --trust-only

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
has "claims" "claim job_workflow_ref: trungleviet-agilityio/sis-platform/.github/workflows/reusable-oidc-smoke.yml@$sha_a"
lacks "claims never print the token" ".sig"
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
lacks "the negative test never prints the account" "$fake"
write_aws 0 ""
expect_fail "a role that accepts the token" "the call succeeded, it must be denied" neg_env "$denied" exa-dev-gha-apply
write_aws 255 "Could not connect to the endpoint URL"
expect_fail "a network error" "failed for a reason other than AccessDenied" neg_env "$denied" exa-dev-gha-apply
expect_fail "an empty account" "ACCOUNT is empty" \
  oidc_env env ACCOUNT="" REGION=ap-southeast-1 "$denied" exa-dev-gha-apply
expect_fail "a bad role name" "is not a <prefix>-<env>-gha-<kind> name" neg_env "$denied" 'x;y'

log "redact_ids and tf-run.sh"
expect_ok "redact_ids" "arn:aws:iam::<account>:role/x id <account> sha a<account>3b" \
  piped "arn:aws:iam::${fake}:role/x id 1234-5678-9012 sha a1234567890123b" redact_ids
cfg="$tmp/terraformrc"
cp "$ROOT/scripts/platform/terraformrc" "$cfg"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >>"%s/tf-args"\nif [ "${TF_STUB_FAIL:-}" = "$2" ]; then echo "Error: AccessDenied for arn:aws:iam::%s:role/r in 1234-5678-9012"; exit 1; fi\necho "raw output for %s"\n' \
  "$tmp" "$fake" "$fake" >"$bin/terraform"
chmod +x "$bin/terraform"
tfrun="$ROOT/scripts/platform/tf-run.sh"
tf_env() { PATH="$bin:$PATH" RUNNER_TEMP="$tmp" TF_CLI_CONFIG_FILE="$cfg" "$@"; }
expect_ok "a successful command prints no raw output" "terraform plan succeeded" tf_env "$tfrun" plan -chdir=x plan
lacks "success prints nothing raw" "raw output for" "$fake"
expect_fail "a failing command prints redacted output" "terraform apply failed (exit 1)" \
  tf_env env TF_STUB_FAIL=apply "$tfrun" apply -chdir=x apply
has "failure output" "arn:aws:iam::<account>:role/r in <account>"
lacks "failure output is redacted" "$fake" "1234-5678-9012"
expect_fail "no CLI config" "TF_CLI_CONFIG_FILE must name the platform CLI config" \
  env PATH="$bin:$PATH" TF_CLI_CONFIG_FILE= "$tfrun" plan -chdir=x plan
expect_fail "a bad label" "label must be" tf_env "$tfrun" "Plan;x" plan

log "tf-init.sh with a stub terraform"
work="$tmp/work"
mkdir -p "$work/infra/envs/dev"
init_env() {
  (cd "$work" && tf_env env ACCOUNT="$fake" ENV_NAME=dev REGION=ap-southeast-1 PREFIX=exa \
    RELEASE_SHA="$sha_a" TF_DATA_DIR="$tmp/data" "$@")
}
initsh="$ROOT/scripts/platform/tf-init.sh"
expect_fail "no lock file" "is not committed" init_env "$initsh" sources
touch "$work/infra/envs/dev/.terraform.lock.hcl"
: >"$tmp/tf-args"
expect_ok "sources pass" "sources resolved and validated, no backend and no credentials used" \
  init_env env ACCOUNT= "$initsh" sources
cp "$tmp/tf-args" "$tmp/out"
has "sources pass runs" "-backend=false" "-lockfile=readonly" "validate"
lacks "sources pass uses no backend config" "bucket="
: >"$tmp/tf-args"
expect_ok "backend pass" "initialized with the composed backend" init_env "$initsh" backend
lacks "backend pass never prints the account" "$fake"
cp "$tmp/tf-args" "$tmp/out"
has "backend pass" "bucket=exa-dev-tfstate-${fake}-ap-southeast-1-an" "key=envs/dev/terraform.tfstate" \
  "-lockfile=readonly" "use_path_style=true" "use_lockfile=true"
expect_fail "backend with an empty account" "ACCOUNT is empty" init_env env ACCOUNT= "$initsh" backend
expect_fail "a bad env" "ENV_NAME must match" init_env env ENV_NAME=Dev "$initsh" sources
expect_fail "no mode" "usage:" init_env "$initsh"

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
