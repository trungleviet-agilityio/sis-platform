#!/usr/bin/env bash
# Credit: adapted from ship-it-serverless scripts/tf/init.sh (lab ADR 0006, G15).
# Initialize the env root of a consumer for the reusable Terraform workflows, in two passes (ADR 0002 T3, M7, AB4):
#   sources  before any credential: `init -backend=false -lockfile=readonly`, then scripts/tf/resolved-sources.sh
#            (local modules or sis-platform at the lock's release_sha; hashicorp providers only), then validate.
#            Only the registry and github.com are reached; nothing from the caller runs with a role yet.
#   backend  after the role is assumed: init again with the backend composed here at run time and never
#            committed (the state bucket name holds the account ID), then resolved-sources.sh again.
#     bucket       <prefix>-<env>-tfstate-<account>-<region>-an   (account regional namespace, account-bootstrap T3)
#     key          envs/<env>/terraform.tfstate                   (the only key the CI roles may touch)
#     use_lockfile true                                           (S3 native lock, key <state key>.tflock)
#     use_path_style true  the endpoint is s3.<region>.amazonaws.com, so harden-runner allows one exact host
#                          without the project prefix (ADR 0002 H3 permits only the account secret and the region)
# The consumer root `infra/envs/<env>/` declares an empty `backend "s3" {}` and commits `.terraform.lock.hcl`.
# Terraform output goes through scripts/platform/tf-run.sh (not printed raw); the account is masked.
#
# Usage: ENV_NAME=dev RELEASE_SHA=... TF_DATA_DIR=... TF_CLI_CONFIG_FILE=... scripts/platform/tf-init.sh sources
#        ... plus ACCOUNT=... REGION=... PREFIX=...                           scripts/platform/tf-init.sh backend

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

mode="${1:-}"
if [ $# -ne 1 ] || { [ "$mode" != "sources" ] && [ "$mode" != "backend" ]; }; then
  die "usage: scripts/platform/tf-init.sh sources|backend (see the header for the environment)"
fi
env_name="${ENV_NAME:-}" release_sha="${RELEASE_SHA:-}"
[[ "$env_name" =~ ^[a-z][a-z0-9]{1,7}$ ]] || die "ENV_NAME must match ^[a-z][a-z0-9]{1,7}\$ (ADR 0002 AA1)"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || die "RELEASE_SHA must be the 40-hex platform.lock release_sha"
[ -n "${TF_DATA_DIR:-}" ] || die "TF_DATA_DIR must be set (resolved-sources.sh reads it after init)"

dir="infra/envs/${env_name}"
[ -d "$dir" ] || die "no Terraform root at ${dir} in the caller repository"
[ -f "$dir/.terraform.lock.hcl" ] || die "${dir}/.terraform.lock.hcl is not committed (init runs with -lockfile=readonly)"
run_tf="$(dirname "$0")/tf-run.sh"
sources="$(dirname "$0")/../tf/resolved-sources.sh"

if [ "$mode" = "sources" ]; then
  "$run_tf" init-sources -chdir="$dir" init -input=false -no-color -lockfile=readonly -backend=false
  "$sources" "$dir" "$TF_DATA_DIR" "$release_sha"
  "$run_tf" validate -chdir="$dir" validate -no-color
  ok "${dir}: sources resolved and validated, no backend and no credentials used"
  exit 0
fi

account="${ACCOUNT:-}" region="${REGION:-}" prefix="${PREFIX:-}"
[ -n "$account" ] || die "ACCOUNT is empty (the AWS_ACCOUNT_ID secret was not passed)"
mask "$account"
[[ "$account" =~ ^[0-9]{12}$ ]] || die "ACCOUNT is not a 12-digit account ID"
[[ "$region" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]] || die "REGION is not a region name"
[[ "$prefix" =~ ^[a-z][a-z0-9-]{1,40}$ ]] || die "PREFIX is not a project prefix"

"$run_tf" init-backend -chdir="$dir" init -input=false -no-color -lockfile=readonly \
  -backend-config="bucket=${prefix}-${env_name}-tfstate-${account}-${region}-an" \
  -backend-config="key=envs/${env_name}/terraform.tfstate" \
  -backend-config="region=${region}" \
  -backend-config="use_lockfile=true" \
  -backend-config="use_path_style=true" \
  -backend-config="encrypt=true"
"$sources" "$dir" "$TF_DATA_DIR" "$release_sha"
ok "${dir}: initialized with the composed backend"
