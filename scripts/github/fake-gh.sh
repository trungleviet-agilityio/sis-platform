#!/usr/bin/env bash
# Stand-in for `gh` in the self-test (copied to a temp dir as `gh` and put first on PATH). It serves the recorded JSON
# under scripts/github/fixtures and rejects anything that is not exactly `gh api -H <h> -H <h> /repos/<o>/<r>/<path>`,
# which is how the self-test proves the audit makes GET requests only.
# Env: FAKE_GH_FIXTURES (fixtures dir), FAKE_GH_CASE (overlay dir name), FAKE_GH_LOG (file that records each path).
set -euo pipefail

bad() { echo "fake-gh: $*" >&2; exit 97; }

[ "${1:-}" = "api" ] || bad "only 'gh api' is allowed, got: ${1:-}"
shift
while [ $# -gt 1 ]; do
  [ "$1" = "-H" ] || bad "forbidden argument: $1"
  shift 2
done
[ $# -eq 1 ] || bad "missing path"
path="$1"
case "$path" in
  /repos/*/*) ;;
  *) bad "not a repository path: $path" ;;
esac

echo "$path" >>"$FAKE_GH_LOG"
rest="${path#/repos/}"
rest="${rest#*/}"  # drop owner
case "$rest" in
  */*) rest="${rest#*/}" ;; # drop repo
  *) rest="" ;;
esac
rest="${rest%%\?*}"
name="${rest//\//__}"
[ -n "$name" ] || name="repo"

if [ -e "$FAKE_GH_FIXTURES/$FAKE_GH_CASE/$name.404" ]; then
  echo "gh: Not Found (HTTP 404)" >&2
  exit 1
fi
for dir in "$FAKE_GH_CASE" good; do
  if [ -f "$FAKE_GH_FIXTURES/$dir/$name.json" ]; then
    cat "$FAKE_GH_FIXTURES/$dir/$name.json"
    exit 0
  fi
done
echo "gh: Not Found (HTTP 404): no fixture for $name" >&2
exit 1
