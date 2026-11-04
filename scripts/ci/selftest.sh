#!/usr/bin/env bash
# Self-test of the repo guard (scripts/ci/check_repo.py), run by `make lint`. Fixtures live under
# scripts/ci/fixtures/: the good ones and the real files must pass, every bad-* fixture must fail with its message.
#   - ADR 0002 H1 to H8 and H10: unpinned or uncommented `uses:` (flow style too), permissions, triggers,
#     harden-runner position and policy, sis-platform checkout, concurrency, `.platform/` closure coverage
#   - a Makefile target whose name contains apply or destroy
# Usage: scripts/ci/selftest.sh   (uses .venv-ci/bin/python when present, else python3 with PyYAML)

# SC2016: the single-quoted `$(...)`, `$ROOT` and `${{ }}` strings are literal fixture text, not expansions.
# shellcheck disable=SC2016
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -eq 0 ] || die "usage: scripts/ci/selftest.sh"
fx="$ROOT/scripts/ci/fixtures"
guard="$ROOT/scripts/ci/check_repo.py"
py="python3"
if [ -x "$ROOT/.venv-ci/bin/python" ]; then py="$ROOT/.venv-ci/bin/python"; fi
"$py" -c 'import yaml' 2>/dev/null || die "PyYAML missing for $py. Run: make venv"

# expect_pass <kind> <file>
expect_pass() {
  "$py" -I "$guard" "$1" "$2" >/dev/null 2>&1 || die "selftest: $2 should pass the $1 guard but failed"
}

# expect_fail <kind> <file> <message fragment>
expect_fail() {
  local out rc=0
  out="$(trap - ERR; "$py" -I "$guard" "$1" "$2" 2>&1)" || rc=$?
  [ "$rc" -ne 0 ] || die "selftest: $2 should fail the $1 guard but passed"
  case "$out" in
    *"$3"*) ;;
    *) die "selftest: $2 failed without the message '$3'. Got: $out" ;;
  esac
}

log "guard fixtures"
expect_pass workflow "$fx/good.yml"
expect_fail workflow "$fx/bad-unpinned.yml" "40-hex"
expect_fail workflow "$fx/bad-unpinned-flow.yml" "uses 'actions/checkout@v7' is not pinned by a 40-hex SHA"
expect_fail workflow "$fx/bad-no-version-comment.yml" "has no '# vX.Y.Z' version comment"
expect_fail workflow "$fx/bad-no-permissions.yml" "permissions: {}"
expect_fail workflow "$fx/bad-trigger.yml" "pull_request_target"
expect_fail workflow "$fx/bad-trigger-dispatch.yml" "workflow_dispatch"
expect_fail workflow "$fx/bad-permissions-write.yml" "permissions: {}"
expect_fail workflow "$fx/bad-write-all.yml" "permissions 'write-all' is not allowed"
expect_fail workflow "$fx/bad-read-all.yml" "permissions 'read-all' is not allowed"
expect_fail workflow "$fx/bad-id-token-no-assume.yml" "id-token: write on a job that neither assumes a role"
expect_fail workflow "$fx/bad-harden-not-first.yml" "the first step is not step-security/harden-runner"
expect_fail workflow "$fx/bad-harden-no-block.yml" "so egress-policy must be block"
expect_fail workflow "$fx/bad-harden-wildcard.yml" "holds a wildcard (list exact hosts)"
expect_fail workflow "$fx/bad-harden-expression.yml" "uses the expression 'vars.AWS_REGION'"
expect_fail workflow "$fx/bad-harden-secret-audit.yml" "reads a secret in a job without credentials"
expect_fail workflow "$fx/bad-checkout-no-sha.yml" 'must use ref: ${{ job.workflow_sha }}'
expect_fail workflow "$fx/bad-checkout-no-sparse.yml" "must set sparse-checkout (H5)"
expect_fail workflow "$fx/bad-no-concurrency.yml" "needs a concurrency group with cancel-in-progress: false"
expect_fail workflow "$fx/bad-cancel-credentialed.yml" "concurrency cancel-in-progress must be false"
expect_fail workflow "$fx/bad-cancel-push.yml" "concurrency cancels in progress for pushes"
expect_pass workflow "$fx/reusable-good.yml"
expect_fail workflow "$fx/reusable-bad-no-family.yml" "must be gated by if: needs.resolve.outputs.family"
expect_fail workflow "$fx/reusable-bad-trigger.yml" "declares trigger 'push' (only workflow_call is allowed)"
expect_pass workflow "$fx/examples/consumer/.github/workflows/good.yml"
expect_fail workflow "$fx/examples/consumer/.github/workflows/bad-input.yml" "workflow_dispatch input 'ref' is not allowed"
expect_fail workflow "$fx/examples/consumer/.github/workflows/bad-env-type.yml" "input 'env' must be type: choice"
expect_pass makefile "$fx/Makefile.good"
expect_fail makefile "$fx/Makefile.bad-apply" "apply"
expect_fail makefile "$fx/Makefile.bad-destroy" "destroy"
expect_fail workflow "$fx/does-not-exist.yml" "cannot read"
expect_pass repo "$fx/repo-good"
expect_fail repo "$fx/repo-bad" "x.yaml: uses 'actions/checkout@v7' is not pinned"
expect_fail repo "$fx/repo-bad" "action.yml: uses 'actions/cache@v4' is not pinned"

# Inline fixtures: a duplicate key, and an account-ID host built at run time (the placeholder 111111111111 is
# allowed by the no-aws-account-id hook, so it can sit in this file).
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
printf 'name: dup\non:\n  pull_request:\non:\n  push:\npermissions: {}\njobs: {}\n' >"$tmp/dup.yml"
expect_fail workflow "$tmp/dup.yml" "duplicate key in a mapping"
sed 's#sts.eu-west-1.amazonaws.com:443#111111111111.dkr.ecr.eu-west-1.amazonaws.com:443#' \
  "$fx/reusable-good.yml" >"$tmp/reusable-account.yml"
expect_fail workflow "$tmp/reusable-account.yml" "holds a 12-digit literal"

log "closure coverage (H6) on a fixture git repository"
repo="$tmp/repo"
wf="$repo/.github/workflows/reusable-x.yml"
closure_file="$repo/scripts/release/closure.txt"
mkdir -p "$repo/scripts/release" "$repo/scripts/platform" "$repo/scripts/tf" "$repo/.github/workflows"
printf ':(glob)scripts/release/closure.txt\n:(glob)scripts/platform/**\n:(glob)scripts/lib.sh\n' >"$closure_file"
printf '# lib\n' >"$repo/scripts/lib.sh"
printf '#!/usr/bin/env bash\nsource "$(dirname "$0")/../lib.sh"\n' >"$repo/scripts/platform/ok.sh"
printf '#!/usr/bin/env bash\nsource "$ROOT/scripts/tf/helper.sh"\n' >"$repo/scripts/platform/sourcing.sh"
printf '# helper\n' >"$repo/scripts/tf/helper.sh"
printf '#!/usr/bin/env bash\n' >"$repo/scripts/tf/policy.sh"
git -C "$repo" init -q
git -C "$repo" add -A

# uses_script <path under .platform>: a reusable workflow that runs that script
uses_script() {
  printf 'name: r\non:\n  workflow_call:\npermissions: {}\njobs: {}\n# run: .platform/%s\n' "$1" >"$wf"
}
closure_run() {
  "$py" -I "$guard" closure --repo "$repo" --closure "$closure_file" "$wf" 2>&1
}
expect_closure_pass() {
  closure_run >/dev/null || die "selftest: closure should pass: $1"
}
expect_closure_fail() { # <message fragment>
  local out rc=0
  out="$(trap - ERR; closure_run)" || rc=$?
  [ "$rc" -ne 0 ] || die "selftest: closure should fail with '$1' but passed"
  case "$out" in *"$1"*) ;; *) die "selftest: closure failed without '$1'. Got: $out" ;; esac
}
uses_script scripts/platform/ok.sh
expect_closure_pass "a glob-covered script that sources a covered file"
uses_script scripts/tf/policy.sh
expect_closure_fail "scripts/tf/policy.sh is not covered by"
uses_script scripts/platform/sourcing.sh
expect_closure_fail "sources scripts/tf/helper.sh, which is not covered by"
git -C "$repo" mv scripts/platform/ok.sh scripts/platform/renamed.sh
uses_script scripts/platform/ok.sh
expect_closure_fail ".platform/scripts/platform/ok.sh is not a tracked file"
uses_script scripts/platform/renamed.sh
expect_closure_pass "a renamed script under its new name"
rm -f "$closure_file"
expect_closure_fail "closure file"

log "guard on the real repository"
expect_pass repo "$ROOT"
ok "repo guard self-tests pass"
