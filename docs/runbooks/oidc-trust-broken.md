# Runbook: OIDC trust is broken

Use when a workflow fails at "Configure AWS credentials" with `Not authorized to perform
sts:AssumeRoleWithWebIdentity` or AccessDenied on assume-role, or when the checkpoint negative test (step 7)
unexpectedly passes. No secret values and no account IDs belong in this file or in tickets: use labels (`dev`,
`prod`).

## 1. Decide which way it is broken

| Symptom | Meaning | Go to |
|---|---|---|
| A job that should assume a role is denied | Trust too narrow, or the value drifted | 2 |
| A job that should be denied can assume a role | Trust too wide | 5 |
| Only the deploy role is denied in Phase 1 | By design: L3 (c) keeps it inert until Phase 2 | Stop |

## 2. Collect the claims (non-secret, no token)

1. Owner: run the smoke workflow's claims step (`reusable-oidc-smoke.yml` from the canary repo, `main`, `environment: dev`).
2. Record `job_workflow_ref`, `job_workflow_sha`, `sub`, `ref`, `repository_id`.
3. Owner, with Identity Center credentials: compare with the role trust, `aws iam get-role --role-name <prefix>-<env>-gha-<plan|apply|deploy>` and read
   `AssumeRolePolicyDocument`. Check `aud` = `sts.amazonaws.com`, the `sub`, and the `job_workflow_ref` value
   `trungleviet-agilityio/sis-platform/.github/workflows/<file>@<sha>`.

## 3. Common causes

| Cause | Check | Fix |
|---|---|---|
| `workflow_sha` moved, bootstrap not re-applied | `platform.lock` `workflow_sha` vs the SHAs in the trust | Owner re-applies bootstrap with the new SHA in `trusted_workflow_shas` (O10), dev then prod |
| Caller pinned a SHA that is not in `trusted_workflow_shas` | `python3 scripts/platform/check_lock.py --remote .` | Fix the pin or add the SHA through a reviewed PR |
| `job_workflow_ref` format differs from the O9 template | Step 2 value | Patch release that pins the exact observed string; never a wildcard (O12) |
| `environment` missing or wrong on the job | `sub` should read `repo:<owner>/<repo>:environment:<env>` | Set `environment` on apply and deploy jobs; plan jobs must not set it |
| Wrong or empty `AWS_ACCOUNT_ID` | The first workflow step fails on an empty value | Fix the environment secret; if it does not resolve cross-owner, use the O13 fallback |
| OIDC provider missing or replaced | `aws iam list-open-id-connect-providers` | Re-apply bootstrap; the provider has `prevent_destroy` |

## 4. Never do these

- Do not widen the trust to a wildcard, to `StringLike`, or to a branch-only subject to "get green".
- Do not attach `*` actions to a role as a workaround.
- Do not `terraform import`, `state mv` or `state rm` from the agent session: the owner runs state commands.

## 5. Trust too wide

1. Treat it as a security incident. Stop approving deployments.
2. Read the trust document and find the condition that is missing or loosened (`StringEquals`, `aud`, `sub`,
   `job_workflow_ref`).
3. The owner re-applies bootstrap from the last good `release_sha`. If a role is already abused, go to
   `leaked-token-or-bad-commit.md` step 3 (deny and revoke sessions).
4. Check CloudTrail for `AssumeRoleWithWebIdentity` events from subjects outside the trust, in both regions
   (`ap-southeast-1`, `us-east-1`). Paste only `eventName` and `errorCode`.
5. Add a tftest that fails on the loosened condition (T9).

## 6. After the fix

Rerun the checkpoint steps 7 (negative) and 8 (positive) in dev, then prod. Record what changed in the PR, with no
IDs.
