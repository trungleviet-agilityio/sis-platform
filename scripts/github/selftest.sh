#!/usr/bin/env bash
# Self-test of scripts/github/check-settings.sh (A12), run by `make lint`. A fake `gh` serves recorded JSON written by
# hand from the GitHub REST docs (scripts/github/fixtures/good is a passing repo; every other directory overlays one
# change on it). The passing repo must exit 0, every bad case must exit 1 with its specific message, and every request
# must be a plain `gh api -H .. -H .. /repos/..` (the fake rejects any other shape, so a write flag cannot slip in).
# Usage: scripts/github/selftest.sh

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -eq 0 ] || die "usage: scripts/github/selftest.sh"
gh_dir="$ROOT/scripts/github"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cp "$gh_dir/fake-gh.sh" "$tmp/gh"
chmod +x "$tmp/gh"
export FAKE_GH_FIXTURES="$gh_dir/fixtures" FAKE_GH_LOG="$tmp/requests.log"

# run_case <case> <repo> [args...]: sets out and rc
run_case() {
  local c="$1"
  shift
  : >"$FAKE_GH_LOG"
  rc=0
  out="$(trap - ERR; FAKE_GH_CASE="$c" PATH="$tmp:$PATH" "$gh_dir/check-settings.sh" "$@" 2>&1)" || rc=$?
}

expect_pass() {
  run_case "$@"
  [ "$rc" -eq 0 ] || die "selftest: case $1 should pass but exited $rc. Got: $out"
  case "$out" in
    *FAIL*) die "selftest: case $1 passed with a FAIL line. Got: $out" ;;
  esac
}

# expect_fail <case> <message fragment> [repo args...]
expect_fail() {
  local c="$1" msg="$2"
  shift 2
  run_case "$c" "${@:-example-owner/sis-platform-canary}"
  [ "$rc" -eq 1 ] || die "selftest: case $c should exit 1 but exited $rc. Got: $out"
  case "$out" in
    *"FAIL "*"$msg"*) ;;
    *) die "selftest: case $c failed without the message '$msg'. Got: $out" ;;
  esac
}

canary="example-owner/sis-platform-canary"

log "passing repositories"
expect_pass good "$canary"
expect_pass no-envs example-owner/sis-platform
expect_pass good "$canary" --envs dev,prod

log "failing conditions"
expect_fail private-repo "repository is private"
expect_fail push-protection-off "secret scanning push protection is disabled"
expect_fail no-branch-ruleset "no branch ruleset covers the default branch 'main'"
expect_fail branch-ruleset-disabled "branch ruleset 'main protection' enforcement is 'disabled'"
expect_fail branch-missing-nonff "branch ruleset is missing rule non_fast_forward"
expect_fail branch-merge-commits "pull_request rule must allow only squash merges (got: squash,merge)"
expect_fail branch-no-check "required status check 'check' is missing"
expect_fail branch-check-wrong-app "required check 'check' comes from integration 99"
expect_fail branch-bypass "branch ruleset has 1 bypass actor(s)"
expect_fail no-tag-ruleset "no tag ruleset covers refs/tags/v*"
expect_fail tag-missing-update "tag ruleset is missing rule update"
expect_fail env-missing-prod "environment 'prod' not found"
expect_fail env-no-reviewers "environment 'dev' has no required reviewers"
expect_fail env-any-branch "environment 'dev' deployment branches are not restricted to custom branch policies"
expect_fail env-branch-not-main "environment 'prod' branch policy must be exactly main (got: branch:release)"
expect_fail env-extra-secret "environment 'dev' secret 'DEPLOY_ROLE_ARN' is not in the allowlist"
expect_fail env-variable "environment 'prod' variable 'AWS_REGION' is not allowed"
expect_fail env-missing-account-secret "environment 'dev' lacks secret AWS_ACCOUNT_ID"
expect_fail repo-extra-secret "repo secret 'NPM_TOKEN' is not in the allowlist"
expect_fail repo-missing-prod-secret "repo secret 'AWS_ACCOUNT_ID_PROD' is missing"
expect_fail repo-variable "repo variable 'RELEASE_STRATEGY' is not allowed"
expect_fail sha-pinning-off "Actions SHA pinning is not required"
expect_fail sha-pinning-unreported "sha_pinning_required not reported"
expect_fail workflow-token-write "default workflow permissions are 'write', expected 'read'"
expect_fail api-404 "cannot read settings: GET /repos/example-owner/sis-platform-canary/rulesets"

log "usage and read-only guarantees"
run_case good
[ "$rc" -ne 0 ] || die "selftest: no argument should fail"
case "$out" in
  *"usage: scripts/github/check-settings.sh"*) ;;
  *) die "selftest: missing usage message. Got: $out" ;;
esac
run_case good not-a-repo
case "$out" in
  *"repo must be OWNER/REPO"*) ;;
  *) die "selftest: bad repo argument not rejected. Got: $out" ;;
esac
run_case good "$canary"
[ -s "$FAKE_GH_LOG" ] || die "selftest: no request was recorded"
if grep -v '^/repos/example-owner/sis-platform-canary' "$FAKE_GH_LOG" >/dev/null; then
  die "selftest: a request left the repository: $(grep -v '^/repos/example-owner/sis-platform-canary' "$FAKE_GH_LOG")"
fi
# The only gh invocation in the audit must carry no write flag.
if grep -nE -- '"(-X|--method|-f|-F|--input|--field|--raw-field)"' "$gh_dir/check_settings.py" >/dev/null; then
  die "selftest: check_settings.py passes a write flag to gh"
fi
ok "github settings check self-tests pass"
