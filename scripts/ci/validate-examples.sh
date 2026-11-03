#!/usr/bin/env bash
# Run the intake validator over every example: valid ones must exit 0, invalid ones must exit non-zero
# (1 for rule errors, 2 for parse errors; anything but 0 counts). `make validate-examples` calls this.
#
# Usage: scripts/ci/validate-examples.sh
# Env:   PYTHON  interpreter (default: python3)

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -eq 0 ] || die "usage: scripts/ci/validate-examples.sh"
py="${PYTHON:-python3}"
cli="$ROOT/intake/sis_intake/validate.py"
[ -f "$cli" ] || die "intake/sis_intake/validate.py is missing; nothing to validate"

fail=0 n_valid=0 n_invalid=0
for f in "$ROOT"/intake/examples/valid/*.yaml; do
  [ -e "$f" ] || die "no files in intake/examples/valid/"
  n_valid=$((n_valid + 1))
  if ! "$py" "$cli" "$f" >/dev/null 2>&1; then
    printf 'FAIL valid example rejected: %s\n' "${f#"$ROOT"/}" >&2
    fail=1
  fi
done
for f in "$ROOT"/intake/examples/invalid/*.yaml; do
  [ -e "$f" ] || die "no files in intake/examples/invalid/"
  n_invalid=$((n_invalid + 1))
  if "$py" "$cli" "$f" >/dev/null 2>&1; then
    printf 'FAIL invalid example accepted: %s\n' "${f#"$ROOT"/}" >&2
    fail=1
  fi
done
[ "$fail" -eq 0 ] || die "example validation failed"
ok "examples: $n_valid valid accepted, $n_invalid invalid rejected"
