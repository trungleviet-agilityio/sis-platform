#!/usr/bin/env bash
# Self-test of the repo guard (scripts/ci/check_repo.py), run by `make lint`. Fixtures live under
# scripts/ci/fixtures/: the good ones and the real files must pass, every bad-* fixture must fail with its message.
#   - a `uses:` line without a 40-hex SHA (local ./ actions excepted)
#   - a workflow without top-level `permissions: {}`
#   - a trigger other than pull_request, push or workflow_call
#   - a Makefile target whose name contains apply or destroy
# Usage: scripts/ci/selftest.sh   (uses .venv-ci/bin/python when present, else python3 with PyYAML)

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
expect_fail workflow "$fx/bad-no-permissions.yml" "permissions: {}"
expect_fail workflow "$fx/bad-trigger.yml" "pull_request_target"
expect_fail workflow "$fx/bad-trigger-dispatch.yml" "workflow_dispatch"
expect_fail workflow "$fx/bad-permissions-write.yml" "permissions: {}"
expect_pass makefile "$fx/Makefile.good"
expect_fail makefile "$fx/Makefile.bad-apply" "apply"
expect_fail makefile "$fx/Makefile.bad-destroy" "destroy"
expect_fail workflow "$fx/does-not-exist.yml" "cannot read"

log "guard on the real repository"
for f in "$ROOT"/.github/workflows/*.yml; do
  if [ -e "$f" ]; then expect_pass workflow "$f"; fi
done
expect_pass makefile "$ROOT/Makefile"
ok "repo guard self-tests pass"
