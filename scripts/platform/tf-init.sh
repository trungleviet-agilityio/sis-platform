#!/usr/bin/env bash
# Credit: adapted from ship-it-serverless scripts/tf/init.sh (lab ADR 0006, G15).
# Initialize and validate the env root of a consumer for the reusable Terraform workflows (ADR 0002 T3, M7). The
# backend is composed here at run time and never committed: the state bucket name holds the account ID. The consumer
# root `infra/envs/<env>/` declares an empty `backend "s3" {}` and commits `.terraform.lock.hcl`.
#   bucket       <prefix>-<env>-tfstate-<account>-<region>-an   (account regional namespace, account-bootstrap T3)
#   key          envs/<env>/terraform.tfstate                   (the only key the CI roles may touch)
#   use_lockfile true                                           (S3 native lock, key <state key>.tflock)
#   use_path_style true    the endpoint is s3.<region>.amazonaws.com, so harden-runner can allow one exact host
#                          without the project prefix (ADR 0002 H3 permits only the account secret and the region)
# The script prints no bucket name, and masks the account in the runner log.
#
# Usage: ACCOUNT=... ENV_NAME=dev REGION=... PREFIX=... TF_DATA_DIR=... scripts/platform/tf-init.sh

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/../lib.sh"

[ $# -eq 0 ] || die "usage: ACCOUNT=... ENV_NAME=... REGION=... PREFIX=... TF_DATA_DIR=... scripts/platform/tf-init.sh"
account="${ACCOUNT:-}" env_name="${ENV_NAME:-}" region="${REGION:-}" prefix="${PREFIX:-}"
[ -n "$account" ] || die "ACCOUNT is empty (the AWS_ACCOUNT_ID secret was not passed)"
if [ -n "${GITHUB_ACTIONS:-}" ]; then printf '::add-mask::%s\n' "$account"; fi
[[ "$account" =~ ^[0-9]{12}$ ]] || die "ACCOUNT is not a 12-digit account ID"
[[ "$env_name" =~ ^[a-z][a-z0-9]{1,7}$ ]] || die "ENV_NAME must match ^[a-z][a-z0-9]{1,7}\$ (ADR 0002 AA1)"
[[ "$region" =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]] || die "REGION is not a region name"
[[ "$prefix" =~ ^[a-z][a-z0-9-]{1,40}$ ]] || die "PREFIX is not a project prefix"
[ -n "${TF_DATA_DIR:-}" ] || die "TF_DATA_DIR must be set (resolved-sources.sh reads it after init)"
require_cmd terraform "run scripts/platform/install-terraform.sh"

dir="infra/envs/${env_name}"
[ -d "$dir" ] || die "no Terraform root at ${dir} in the caller repository"
[ -f "$dir/.terraform.lock.hcl" ] || die "${dir}/.terraform.lock.hcl is not committed (init runs with -lockfile=readonly)"

terraform -chdir="$dir" init -input=false -no-color -lockfile=readonly \
  -backend-config="bucket=${prefix}-${env_name}-tfstate-${account}-${region}-an" \
  -backend-config="key=envs/${env_name}/terraform.tfstate" \
  -backend-config="region=${region}" \
  -backend-config="use_lockfile=true" \
  -backend-config="use_path_style=true" \
  -backend-config="encrypt=true"
terraform -chdir="$dir" validate -no-color
ok "initialized ${dir}"
