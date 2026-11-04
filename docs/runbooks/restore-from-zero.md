# Runbook: restore from zero

Use when an account, the state bucket or the repo is lost or unusable and the platform must be rebuilt. Phase 1
scope: the bootstrap per account and the canary. Workload data restore is a Phase 2 runbook. No account IDs or
secret values go in this file: use labels.

## 0. What is where

| Piece | Source of truth | Lost means |
|---|---|---|
| Code, modules, workflows | The public repo `trungleviet-agilityio/sis-platform` and the consumer repo | Re-clone; tags are immutable |
| Release choice | `platform.yaml`, `platform.lock` in the consumer repo | Re-clone |
| Bootstrap resources | `modules/account-bootstrap` applied by the owner | Rebuild (steps 2 to 4) |
| Terraform state | S3 state bucket in each account (versioned) | Restore a version (step 3) |
| Secrets and account IDs | Keychain (`kc`), GitHub environment secrets | Recreate from the AWS console |

## 1. Decide the case

| Case | Do |
|---|---|
| Repo lost | Re-create from a clone or fork; reapply the `main` and tag rulesets; run `scripts/github/check-settings.sh` |
| State object lost or corrupt, bucket alive | Step 3 |
| State bucket lost, account alive | Steps 2 and 4 with local state, then migrate |
| Account lost | Create a new account under OU `Sandbox`, root MFA, then steps 2 to 5 |

## 2. Prepare

1. Fresh clone at the consumer's `release_sha`. Run `python3 <sis-platform>/scripts/platform/check_lock.py --remote .`.
2. Identity Center admin credentials for the target account (the owner; the agent shell has none).
3. Recreate the gitignored files: `accounts/<env>.tfvars`, `accounts/<env>.backend.hcl` and `backend_override.tf`
   (local backend). Values come from the Keychain and the console.
4. Generate the tfvars:
   `python3 <sis-platform>/intake/sis_intake/validate.py platform.yaml --emit tfvars --env <env> > "$TMPDIR/platform-<env>.tfvars.json"`.

## 3. Restore state from a bucket version

1. List object versions of `envs/<env>/terraform.tfstate` (and `bootstrap/terraform.tfstate`) and pick the last
   good one by time.
2. Copy that version back as the current object. Do not delete versions.
3. Run `terraform plan`. Expect no changes; if there are changes, read them and stop for the owner.

## 4. Rebuild the bootstrap

1. `terraform -chdir=infra/bootstrap init` with the local backend, then `apply` with both var files (checkpoint
   step 6 commands).
2. Remove `backend_override.tf`, then `init -migrate-state -backend-config=accounts/<env>.backend.hcl`.
3. Confirm the SNS subscription, `aws cloudtrail get-trail-status`, and one analyzer in
   `aws accessanalyzer list-analyzers`.
4. If the OIDC provider already exists in the account, set `create_oidc_provider = false` (T2).
5. Never run `terraform import` from the agent session. If resources already exist, the owner imports them.

## 5. Re-establish trust and prove it

1. GitHub: environments `dev` and `prod` with a required reviewer and `main` only; secrets `AWS_ACCOUNT_ID`,
   `AWS_ACCOUNT_ID_DEV`, `AWS_ACCOUNT_ID_PROD`.
2. Run the negative test (checkpoint step 7), then a positive apply (step 8), then
   `scripts/github/check-settings.sh`.
3. Run the A7 CloudTrail query (step 9) in both regions; only the step 7 denials should appear.

## 6. Verify and record

- `make check` green on the restored repo.
- Cost: budget, anomaly monitor and cost allocation tags (step 11) are back.
- Record the time to restore and any step that needed a manual fix, as a PR note. Rehearse this runbook once per
  phase (WA9, WA14).
