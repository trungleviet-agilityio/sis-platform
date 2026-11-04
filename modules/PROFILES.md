# Profiles: the interface between `account-bootstrap` and the runtimes

Specification for ADR 0002 T8 and T11. Phase 1 builds no profile; Phase 2 adds `modules/deploy-profile-<profile>` and
`modules/apply-profile-<kind>` against this page. Fixtures in `scripts/tf/fixtures/policy/` test the linter now.

## Shape

The consumer root `infra/bootstrap` composes the profiles and hands plain JSON to the bootstrap module:

```hcl
module "deploy_profile" {
  source = "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/deploy-profile-lambda-web?ref=<release_sha>"
  # inputs below
}

module "account_bootstrap" {
  source = "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=<release_sha>"

  apply_policy_json         = module.apply_profile.policy_json
  deploy_policy_json        = module.deploy_profile.policy_json
  deploy_profile_name       = module.deploy_profile.name
  ecr_repository_policy_json = module.deploy_profile.ecr_repository_policy_json
  # platform, github_*, trusted_workflow_shas, notification_email ...
}
```

A circular reference is avoided because a profile takes names and the boundary ARN as strings built from the same
`<prefix>-<env>` rule the bootstrap uses (`resource_names` output), not from bootstrap resources. The boundary ARN is
`arn:<partition>:iam::<account>:policy/<prefix>-<env>-workload-boundary`.

## Profile outputs

| Output | Type | Meaning |
|---|---|---|
| `name` | string | The profile name. Must equal the M6 `deploy_role_profile` of the env, or the bootstrap precondition fails |
| `policy_json` | string | One IAM policy document for the apply or deploy role |
| `ecr_repository_policy_json` | string or null | Deploy profiles only: the repository policy (for Lambda, the service pull statement) |

## Profile inputs

`prefix`, `env`, `region`, `account_id`, `partition` (defaults `aws`), and `boundary_arn`. A profile never takes an ARN
it cannot derive from those.

## Rules every composed policy follows

The bootstrap module checks the first group (T8, cheap structural checks). `scripts/tf/policy.py` checks all of them
(T11) on fixtures in Phase 1 (`make tf-check`) and on `terraform show -json` in the reusable plan job.

| ID | Rule |
|---|---|
| P01 | No `Allow` with a `*` action |
| P02 | No `Allow` with `iam:*` |
| P03 | No `Allow` of `sts:AssumeRole*` (role chaining is also denied by guardrail G3) |
| P04 | No `NotAction` or `NotResource` on an `Allow` statement |
| P05 | `Resource: "*"` only for actions with no resource-level support (the allowlist in `policy.py`) |
| P06 | `iam:CreateRole`, `iam:PutRolePolicy`, `iam:AttachRolePolicy`, `iam:PutRolePermissionsBoundary` only with the condition `iam:PermissionsBoundary` equal to the boundary ARN |
| P07 | `iam:PassRole` only with an `iam:PassedToService` condition |
| P08 | No write to the boundary policy itself (policy create, delete, version and tag actions on its ARN) |
| P09 | No `iam:DeleteRolePermissionsBoundary` (it would strip the boundary) |
| P00 | A policy that is unknown at plan time cannot be checked and fails closed (`--unknown warn` downgrades it) |

## The boundary

`account-bootstrap` creates `<prefix>-<env>-workload-boundary` and outputs `workload_boundary_arn`. It is the ceiling
for every workload role (Lambda execution role, ECS task and execution role): log writes for the env, image pull from
the env repositories, and the env secrets. The apply profile may create a workload role only with
`"permissions_boundary" = <boundary ARN>`, and its policy must carry the P06 condition, so a bad apply cannot mint an
unbounded role. Guardrail G4 stops every CI role from editing the boundary, the gha roles and the OIDC provider.
