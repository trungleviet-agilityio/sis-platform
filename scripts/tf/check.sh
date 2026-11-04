#!/usr/bin/env bash
# Credit: adapted from ship-it-safely scripts/tf/check.sh (lab ADR 0001 D12, D16, ADR 0007).
# Offline Terraform checks for every module under modules/ (ADR 0002, H9):
#   1. the policy.py linter tests and the resolved-sources self-test;
#   2. no provider or backend block in a module (the consumer root owns them, T1);
#   3. a README.md with terraform-docs markers whose generated tables are current;
#   4. terraform fmt -check;
#   5. per module: init without a backend, resolved sources, validate, `terraform test` (mock providers), tflint.
# Each module gets its own temporary TF_DATA_DIR, so a real `init` in a checkout is never read or written.
# Never plans or applies: no AWS credentials are needed or used.
#
# Usage: scripts/tf/check.sh [dir ...]   (default: every directory under modules/ that holds *.tf)

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

require_cmd terraform "mise install (pinned in mise.toml)"
require_cmd tflint "mise install (pinned in mise.toml)"
require_cmd terraform-docs "mise install (pinned in mise.toml)"
require_cmd jq "brew install jq"
require_cmd python3 "mise install"

modules_root="$ROOT/modules"
tflint_config="$modules_root/.tflint.hcl"
docs_config="$modules_root/.terraform-docs.yml"

tmp_root="$(mktemp -d)"
trap 'rm -rf "$tmp_root"' EXIT
# A persistent provider cache keeps repeat runs offline once the AWS provider has been downloaded once.
TF_PLUGIN_CACHE_DIR="${TF_PLUGIN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/sis-platform/terraform-plugins}"
export TF_PLUGIN_CACHE_DIR
mkdir -p "$TF_PLUGIN_CACHE_DIR"

dirs=()
failed=()
if [ $# -gt 0 ]; then
  for d in "$@"; do dirs+=("$d"); done
else
  while IFS= read -r d; do dirs+=("$d"); done < <(
    find "$modules_root" -name '*.tf' -not -path '*/.terraform/*' -not -path '*/tests/*' -exec dirname {} \; | sort -u
  )
fi

if [ ${#dirs[@]} -eq 0 ]; then
  warn() { printf 'warn %s\n' "$*" >&2; }
  warn "no Terraform files under modules/ yet, nothing to check"
  exit 0
fi

log "policy.py tests"
python3 -m unittest discover -s "$ROOT/scripts/tf" -p 'test_policy.py'

log "resolved-sources self-test"
"$ROOT/scripts/tf/resolved-sources-selftest.sh"

log "no provider or backend block in a module (T1)"
hits="$(grep -rEn --include='*.tf' --exclude-dir=.terraform '^[[:space:]]*(provider|backend)[[:space:]]+"' "${dirs[@]}" || true)"
if [ -n "$hits" ]; then
  printf '%s\n' "$hits" >&2
  die "a module must not hold a provider or backend block; the consumer root owns them"
fi

# Every module documents itself; the tables between the markers come from terraform-docs and must be current.
for dir in "${dirs[@]}"; do
  readme="$dir/README.md"
  if [ ! -f "$readme" ]; then
    failed+=("${dir#"$ROOT"/} (README.md missing)")
  elif ! grep -q 'BEGIN_TF_DOCS' "$readme"; then
    failed+=("${dir#"$ROOT"/} (README.md has no BEGIN_TF_DOCS marker)")
  elif ! terraform-docs --config "$docs_config" --output-check "$dir" >/dev/null; then
    failed+=("${dir#"$ROOT"/} (README tables are stale; run: terraform-docs --config modules/.terraform-docs.yml ${dir#"$ROOT"/})")
  fi
done

log "terraform fmt -check"
terraform fmt -check -recursive "$modules_root" || die "unformatted files; run: terraform fmt -recursive modules"

for dir in "${dirs[@]}"; do
  name="${dir#"$ROOT"/}"
  log "$name"
  data_dir="$tmp_root/data/$(printf '%s' "$name" | tr '/' '_')"
  mkdir -p "$data_dir"
  export TF_DATA_DIR="$data_dir"
  # Each step is guarded so one broken directory does not hide the rest; the summary fails the run.
  if ! terraform -chdir="$dir" init -backend=false -input=false >/dev/null; then
    failed+=("$name (init)")
    continue
  fi
  # What init resolved, not what the text says: remote modules and non-hashicorp providers fail here.
  if ! "$ROOT/scripts/tf/resolved-sources.sh" "$dir" "$data_dir"; then
    failed+=("$name (resolved sources)")
    continue
  fi
  if ! terraform -chdir="$dir" validate -no-color >/dev/null; then
    failed+=("$name (validate)")
    continue
  fi
  if compgen -G "$dir/tests/*.tftest.hcl" >/dev/null || compgen -G "$dir/*.tftest.hcl" >/dev/null; then
    if ! terraform -chdir="$dir" test; then
      failed+=("$name (test)")
      continue
    fi
  fi
  if ! tflint --config="$tflint_config" --chdir="$dir"; then
    failed+=("$name (tflint)")
    continue
  fi
  ok "$name"
done

if [ ${#failed[@]} -gt 0 ]; then
  for f in "${failed[@]}"; do printf '  - %s\n' "$f" >&2; done
  die "${#failed[@]} Terraform check(s) failed"
fi
ok "all ${#dirs[@]} Terraform directories pass"
