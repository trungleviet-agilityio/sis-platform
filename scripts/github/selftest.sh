#!/usr/bin/env bash
# Self-test of scripts/github/check-settings.sh (A12), run by `make lint`. A fake `gh` serves recorded JSON written by
# hand from the GitHub REST docs (scripts/github/fixtures/good is a passing repo; every other directory overlays one
# change on it). The passing repo must exit 0, every bad case must exit 1 with its specific message and failure count,
# every WARN case must exit 0, and every request must be a plain `gh api -H .. -H .. /repos/..` (the fake rejects any
# other shape, so a write flag cannot slip in).
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

canary="example-owner/sis-platform-canary"

# run_case <case> <repo> [args...]: sets out and rc
run_case() {
  local c="$1"
  shift
  : >"$FAKE_GH_LOG"
  rc=0
  out="$(trap - ERR; FAKE_GH_CASE="$c" PATH="$tmp:$PATH" "$gh_dir/check-settings.sh" "$@" 2>&1)" || rc=$?
}

# expect_pass <case> <repo> [args...]: exit 0, no FAIL line
expect_pass() {
  run_case "$@"
  [ "$rc" -eq 0 ] || die "selftest: case $1 should pass but exited $rc. Got: $out"
  case "$out" in
    *FAIL*) die "selftest: case $1 passed with a FAIL line. Got: $out" ;;
    *"0 failure(s)"*) ;;
    *) die "selftest: case $1 printed no summary. Got: $out" ;;
  esac
}

# expect_warn <case> <message fragment> [repo args...]: exit 0 and a WARN line with the message
expect_warn() {
  local c="$1" msg="$2"
  shift 2
  run_case "$c" "${@:-$canary}"
  [ "$rc" -eq 0 ] || die "selftest: case $c should pass with a warning but exited $rc. Got: $out"
  case "$out" in
    *"WARN "*"$msg"*) ;;
    *) die "selftest: case $c gave no WARN with '$msg'. Got: $out" ;;
  esac
  case "$out" in
    *FAIL*) die "selftest: case $c has a FAIL line. Got: $out" ;;
  esac
}

# expect_fail <case> <failure count> <message fragment> [repo args...]
expect_fail() {
  local c="$1" count="$2" msg="$3"
  shift 3
  run_case "$c" "${@:-$canary}"
  [ "$rc" -eq 1 ] || die "selftest: case $c should exit 1 but exited $rc. Got: $out"
  case "$out" in
    *"FAIL "*"$msg"*) ;;
    *) die "selftest: case $c failed without the message '$msg'. Got: $out" ;;
  esac
  case "$out" in
    *"$count failure(s)"*) ;;
    *) die "selftest: case $c should report '$count failure(s)'. Got: $out" ;;
  esac
}

log "passing repositories"
expect_pass good "$canary"
expect_pass no-envs example-owner/sis-platform
expect_pass good "$canary" --envs dev,prod
expect_pass good "$canary" --envs ''
expect_pass tag-include-all "$canary"
expect_pass tag-include-star "$canary"
expect_pass two-rulesets "$canary"

log "failing conditions"
expect_fail private-repo 1 "repository is private"
expect_fail push-protection-off 1 "secret scanning push protection is disabled"
expect_fail no-branch-ruleset 1 "no branch ruleset covers the default branch 'main'"
expect_fail branch-ruleset-disabled 1 "branch ruleset 'main protection' enforcement is 'disabled'"
expect_fail branch-missing-nonff 1 "branch ruleset is missing rule non_fast_forward"
expect_fail branch-merge-commits 1 "pull_request rule must allow only squash merges (got: merge,squash)"
expect_fail two-rulesets-merge 1 "pull_request rule must allow only squash merges (got: merge)"
expect_fail branch-no-check 1 "required status check 'check' is missing"
expect_fail branch-check-wrong-app 1 "required check 'check' comes from integration 99"
expect_fail branch-bypass 1 "branch ruleset has 1 bypass actor(s)"
expect_fail no-tag-ruleset 1 "no tag ruleset covers refs/tags/v*"
expect_fail tag-missing-update 1 "tag ruleset is missing rule update"
expect_fail tag-missing-deletion 1 "tag ruleset is missing rule deletion"
expect_fail tag-bypass 1 "tag ruleset has 1 bypass actor(s); none are allowed (a bypass defeats immutable tags)"
expect_fail env-missing-prod 1 "environment 'prod' not found"
expect_fail env-no-reviewers 1 "environment 'dev' has no required reviewers"
expect_fail extra-env 1 "environment 'staging' has no required reviewers"
expect_fail env-any-branch 1 "environment 'dev' deployment branches are not restricted to custom branch policies"
expect_fail env-branch-not-main 1 "environment 'prod' branch policy must be exactly main (got: branch:release)"
expect_fail env-extra-secret 1 "environment 'dev' secret 'DEPLOY_ROLE_ARN' is not in the allowlist"
expect_fail env-variable 1 "environment 'prod' variable 'AWS_REGION' is not allowed"
expect_fail env-missing-account-secret 1 "environment 'dev' lacks secret AWS_ACCOUNT_ID"
expect_fail bad-env-name 1 "environment name '../x' is not a valid name; not queried"
expect_fail repo-extra-secret 1 "repo secret 'NPM_TOKEN' is not in the allowlist"
expect_fail repo-missing-prod-secret 1 "repo secret 'AWS_ACCOUNT_ID_PROD' is missing"
expect_fail repo-variable 1 "repo variable 'RELEASE_STRATEGY' is not allowed"
expect_fail sha-pinning-off 1 "Actions SHA pinning is not required"
expect_fail sha-pinning-unreported 1 "sha_pinning_required not reported"
expect_fail workflow-token-write 1 "default workflow permissions are 'write', expected 'read'"
# One unreadable endpoint fails the checks that need it (branch and tag) and the others still run.
expect_fail api-404 2 "branch ruleset check could not run: GET /repos/example-owner/sis-platform-canary/rulesets"
expect_fail garbage-repo 1 "repository check could not run: unexpected JSON shape"

log "warnings"
expect_warn private-repo "repository is private" "$canary" --envs ''
expect_warn check-integration-null "required check 'check' accepts any source"
expect_warn no-security-analysis "security_and_analysis not reported"
expect_warn bypass-absent "branch ruleset bypass_actors not reported"
expect_warn tag-bypass-absent "tag ruleset bypass_actors not reported"
expect_warn org-visible "org-level secret 'SHARED_TOKEN' is visible to this repo"
expect_warn org-visible "org-level variable 'SHARED_FLAG' is visible to this repo"
expect_warn org-api-404 "org-level secrets not readable"

log "usage and read-only guarantees"
run_case good
[ "$rc" -ne 0 ] || die "selftest: no argument should fail"
case "$out" in
  *"usage: scripts/github/check-settings.sh"*) ;;
  *) die "selftest: missing usage message. Got: $out" ;;
esac
for bad in not-a-repo owner/.. ./repo a/b/c; do
  run_case good "$bad"
  [ "$rc" -eq 2 ] || die "selftest: repo argument '$bad' should be rejected with 2, got $rc. Got: $out"
  case "$out" in
    *"repo must be OWNER/REPO"*) ;;
    *) die "selftest: repo argument '$bad' gave the wrong message. Got: $out" ;;
  esac
done
run_case good "$canary" --envs 'dev,../x'
[ "$rc" -eq 2 ] || die "selftest: bad --envs should exit 2, got $rc. Got: $out"
case "$out" in
  *"invalid environment name '../x' in --envs"*) ;;
  *) die "selftest: bad --envs gave the wrong message. Got: $out" ;;
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
