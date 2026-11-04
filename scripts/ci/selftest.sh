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
expect_fail workflow "$fx/reusable-bad-family-or.yml" "must be gated by if: needs.resolve.outputs.family"
expect_fail workflow "$fx/reusable-bad-checkout-expr.yml" "must set repository to the literal trungleviet-agilityio/sis-platform, not an expression (O11)"
expect_fail workflow "$fx/reusable-bad-checkout-expr.yml" 'must use ref: ${{ job.workflow_sha }}'
expect_fail workflow "$fx/reusable-bad-workdir.yml" "working-directory under .platform"
expect_fail workflow "$fx/reusable-bad-cd.yml" "refers to .platform without a trailing slash"
expect_fail workflow "$fx/reusable-bad-var.yml" "refers to .platform without a trailing slash"
expect_fail workflow "$fx/reusable-bad-local-uses.yml" "uses the local action './.github/actions/local'"
expect_fail workflow "$fx/bad-cancel-push-job.yml" "job 'a': concurrency cancels in progress for pushes"
expect_fail workflow "$fx/bad-permissions-case.yml" "id-token: write on a job that neither assumes a role"
expect_fail workflow "$fx/bad-write-all-case.yml" "permissions 'Write-All' is not allowed"
expect_fail workflow "$fx/bad-id-token-echo.yml" "id-token: write on a job that neither assumes a role"
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
sed "s/family == 'lambda'/family == 'lambda' \&\& inputs.go/" "$fx/reusable-good.yml" >"$tmp/reusable-and.yml"
expect_pass workflow "$tmp/reusable-and.yml"
sed "s/    if: needs/    if: \${{ needs/;s/'lambda'\$/'lambda' }}/" "$fx/reusable-good.yml" >"$tmp/reusable-wrapped.yml"
expect_pass workflow "$tmp/reusable-wrapped.yml"
sed 's#sts.eu-west-1.amazonaws.com:443#111111111111.dkr.ecr.eu-west-1.amazonaws.com:443#' \
  "$fx/reusable-good.yml" >"$tmp/reusable-account.yml"
expect_fail workflow "$tmp/reusable-account.yml" "holds a 12-digit literal"

log "closure coverage (H6) on a fixture git repository"
repo="$tmp/repo"
wf="$repo/.github/workflows/reusable-x.yml"
closure_file="$repo/scripts/release/closure.txt"
mkdir -p "$repo/scripts/release" "$repo/scripts/platform" "$repo/scripts/tf" "$repo/.github/workflows"
printf ':(glob)scripts/release/closure.txt\n:(glob)scripts/platform/**\n:(exclude,glob)scripts/platform/version.py\n:(glob)scripts/lib.sh\n' >"$closure_file"
printf '__version__ = "1"\n' >"$repo/scripts/platform/version.py"
printf '#!/usr/bin/env bash\nsource "$(dirname "$0")/version.py"\n' >"$repo/scripts/platform/sources-excluded.sh"
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
printf '#!/usr/bin/env bash\nif true; then bash ../tf/policy.sh; fi\n' >"$repo/scripts/platform/calls-bash.sh"
printf '#!/usr/bin/env bash\ntrue && source "$ROOT/scripts/tf/helper.sh"\n' >"$repo/scripts/platform/and-source.sh"
printf '#!/usr/bin/env bash\n./sibling.sh\n' >"$repo/scripts/platform/calls-dot.sh"
printf '#!/usr/bin/env bash\nsource "$LIBDIR/lib.sh"\n' >"$repo/scripts/platform/uses-var.sh"
git -C "$repo" add -A
uses_script scripts/platform/ok.sh
expect_closure_pass "a glob-covered script that sources a covered file"
uses_script scripts/tf/policy.sh
expect_closure_fail "scripts/tf/policy.sh is not covered by"
uses_script scripts/platform/sourcing.sh
expect_closure_fail "sources scripts/tf/helper.sh, which is not covered by"
uses_script scripts/platform/calls-bash.sh
expect_closure_fail "sources scripts/tf/policy.sh, which is not covered by"
uses_script scripts/platform/and-source.sh
expect_closure_fail "sources scripts/tf/helper.sh, which is not covered by"
uses_script scripts/platform/calls-dot.sh
expect_closure_fail "sources scripts/platform/sibling.sh, not tracked"
uses_script scripts/platform/uses-var.sh
expect_closure_fail "a path with a variable the closure check cannot resolve"
git -C "$repo" mv scripts/platform/ok.sh scripts/platform/renamed.sh
uses_script scripts/platform/ok.sh
expect_closure_fail ".platform/scripts/platform/ok.sh is not a tracked file"
uses_script scripts/platform/renamed.sh
expect_closure_pass "a renamed script under its new name"
uses_script scripts/platform/version.py
expect_closure_fail ".platform/scripts/platform/version.py is not covered by"
uses_script scripts/platform/sources-excluded.sh
expect_closure_fail "sources scripts/platform/version.py, which is not covered by"
rm -f "$closure_file"
expect_closure_fail "closure file"

log "repo mode refuses a missing or empty root"
# expect_usage_error <root> <message fragment>: exit status 2 with the message
expect_usage_error() {
  local out rc=0
  out="$(trap - ERR; "$py" -I "$guard" repo "$1" 2>&1)" || rc=$?
  [ "$rc" -eq 2 ] || die "selftest: repo $1 should exit 2, got $rc"
  case "$out" in *"$2"*) ;; *) die "selftest: repo $1 failed without '$2'. Got: $out" ;; esac
}
expect_usage_error "$tmp/does-not-exist" "is not a directory"
mkdir -p "$tmp/empty-root"
expect_usage_error "$tmp/empty-root" "nothing to check"

log "install-tf-tools.sh versions match mise.toml"
tools="$ROOT/scripts/ci/install-tf-tools.sh"
# check_tool_versions <mise.toml> <message fragment or empty>: every tool pinned in both files has one version
check_tool_versions() {
  local out rc=0 name var
  for pair in terraform:TERRAFORM tflint:TFLINT terraform-docs:TERRAFORM_DOCS; do
    name="${pair%%:*}"
    var="${pair##*:}_VERSION"
    want="$(sed -n "s/^${name} = \"\(.*\)\"\$/\1/p" "$1")"
    [ -n "$want" ] || continue # not pinned in this mise.toml yet
    have="$(sed -n "s/^${var}=\"\(.*\)\"\$/\1/p" "$tools")"
    [ "$want" = "$have" ] || { echo "install-tf-tools.sh ${var} ${have} differs from mise.toml ${name} ${want}"; rc=1; }
  done
  return "$rc"
}
check_tool_versions "$ROOT/mise.toml" >/dev/null || die "selftest: install-tf-tools.sh versions drifted from mise.toml"
printf '[tools]\nterraform = "0.0.1"\n' >"$tmp/mise.toml"
out="$(check_tool_versions "$tmp/mise.toml" || true)"
case "$out" in *"TERRAFORM_VERSION"*"differs from mise.toml terraform 0.0.1"*) ;; *) die "selftest: drift check did not report. Got: $out" ;; esac
grep -Eq '^[A-Z_]+_SHA256="[0-9a-f]{64}"$' "$tools" || die "selftest: install-tf-tools.sh holds no 64-hex SHA-256 values"

log "no-aws-account-id hook pattern"
"$py" -I - "$ROOT/.pre-commit-config.yaml" <<'PY' || die "selftest: the no-aws-account-id pattern misbehaves"
import re
import sys

import yaml

cfg = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
hook = next(h for r in cfg["repos"] for h in r["hooks"] if h["id"] == "no-aws-account-id")
rx = re.compile(hook["entry"])
# Built from parts so this file does not trip the hook itself.
acct, dashed = "99998888" + "7777", "-".join(["9999", "8888", "7777"])
cases = [(acct, True), (dashed, True), ("1234-5678-9012", False), ("123456789012", False),
         (dashed + "-6666", False), ("uuid-" + dashed, False)]
for text, hit in cases:
    assert bool(rx.search(text)) == hit, (text, hit)
PY

log "guard on the real repository"
expect_pass repo "$ROOT"
ok "repo guard self-tests pass"
