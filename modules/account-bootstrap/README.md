# account-bootstrap

Per-account foundation of a platform environment (ADR 0002, T1 to T11). One module call per account and
environment. The owner applies it by hand with admin credentials; CI never applies it (T10).

Credit: extracted from the `ship-it-safely` and `ship-it-serverless` labs, `infra/terraform/bootstrap`. Each file
header names its source.

## What it creates

- GitHub OIDC provider (`create_oidc_provider`, default true, `prevent_destroy`), or a lookup when the account
  already has one (T2).
- Terraform state bucket: account-regional namespace, versioning, SSE-S3 with SSE-C blocked, TLS-only policy,
  public access block, noncurrent version lifecycle. Keys `envs/<env>/terraform.tfstate` and `bootstrap/` (T3).
- Three roles `<prefix>-<env>-gha-{plan,apply,deploy}` with 3600 second sessions (T4). Trust is exact (`StringEquals`,
  immutable owner and repo IDs, `ref` pinned, `aws:RequestedRegion` pinned):
  - apply trusts `reusable-terraform-apply.yml` and deploy trusts `reusable-release.yml` of the platform repository at
    each SHA in `trusted_workflow_shas` (N and N-1, O9). The deploy file does not exist until Phase 2, so the deploy
    role is inert by design;
  - the nonprod plan role trusts the `pull_request` subject (O14); the prod plan role trusts only `ref:refs/heads/main`
    and `environment:<env>` subjects, never a pull request.
- Plan role: the managed `ReadOnlyAccess` policy plus denies on secret values, SSM parameter reads, every
  `kms:Decrypt` and S3 object reads outside the state keys. The managed policy is not purely read-only, so the denies include the data-plane reads it grants (SQS receive, DynamoDB reads and PartiQL, log queries, Kinesis records, `s3express:CreateSession` and so on). Its only write is the env's `.tflock` object. Accepted
  (O14): the data-returning reads that remain are readable by a same-repo PR author in nonprod, and the nonprod plan
  role can write the lock object (lock interference).
- Guardrails G1 to G8 are attached to all three roles, and G9 (escalation: role writes only with the workload boundary, no boundary removal, `iam:PassRole` only with a service) to apply and deploy, in two managed policies under the 6144 character limit: secret values, SSM parameters, role chaining, IAM writes and
  `iam:PassRole` on the gha roles, boundary and OIDC provider, the bootstrap state key, the audit trail and alert
  resources, the state bucket's own configuration (G7) and the app ECR repository's administration (G8).
- ECR repository `<prefix>-<env>-app`: immutable tags, scan on push, AES256, lifecycle (untagged expire after 14 days,
  newest 20 tagged images in nonprod, 50 in prod) (T5). Promotion is deferred to Phase 2 (T6).
- Budget from the plan with actual and forecast alerts at 80 and 100 percent, a Cost Anomaly Detection monitor, the
  `notify` SNS email topic (T7).
- Detective baseline (T7): multi-region management-event trail, IAM Access Analyzer, GuardDuty only when
  `enable_guardduty` is set, and an EventBridge rule that mails the topic on a refused or unexpected
  `AssumeRoleWithWebIdentity`, and a rule that mails it every Access Analyzer finding.
- Permissions boundary `<prefix>-<env>-workload-boundary`, output `workload_boundary_arn` (T11).

## Contract

The module has no `provider` or `backend` block. The consumer root `infra/bootstrap` owns them, with
`allowed_account_ids` and `default_tags` (`Project`, `Env`, `Tier`, `Owner`, `ManagedBy`, `Platform`,
`PlatformVersion`). The `platform` input is the `platform` key of
`validate.py platform.yaml --emit tfvars --env <e>` (M7); keys the module does not read are ignored.

`apply_policy_json`, `deploy_policy_json` and `ecr_repository_policy_json` come from profile modules in the consumer
root (T8, `../PROFILES.md`). The module only checks them structurally; the full lint is `scripts/tf/policy.py`.

Consumers call the module by commit SHA, never by tag or branch:

```hcl
module "account_bootstrap" {
  source = "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=<release_sha>"
  # ...
}
```

## Tests

`terraform test` runs offline with `mock_provider "aws"`; the only account ID in the fixtures is `123456789012`.
Run everything with `make tf-check`.

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| terraform | >= 1.11, < 2.0 |
| aws | ~> 6.71 |

## Providers

| Name | Version |
| ---- | ------- |
| aws | ~> 6.71 |

## Modules

No modules.

## Resources

| Name | Type |
| ---- | ---- |
| [aws_accessanalyzer_analyzer.account](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/accessanalyzer_analyzer) | resource |
| [aws_budgets_budget.monthly](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/budgets_budget) | resource |
| [aws_ce_anomaly_monitor.services](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ce_anomaly_monitor) | resource |
| [aws_ce_anomaly_subscription.notify](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ce_anomaly_subscription) | resource |
| [aws_cloudtrail.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudtrail) | resource |
| [aws_cloudwatch_event_rule.access_analyzer](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_rule.oidc_unexpected](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_target.access_analyzer](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_event_target.notify](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_ecr_lifecycle_policy.app](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_lifecycle_policy) | resource |
| [aws_ecr_repository.app](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_repository) | resource |
| [aws_ecr_repository_policy.app](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecr_repository_policy) | resource |
| [aws_guardduty_detector.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/guardduty_detector) | resource |
| [aws_iam_openid_connect_provider.github](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_openid_connect_provider) | resource |
| [aws_iam_policy.guardrails](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_policy.guardrails_escalation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_policy.workload_boundary](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_policy) | resource |
| [aws_iam_role.apply](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.deploy](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.plan](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.apply_composed](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.apply_state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.deploy_base](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.deploy_composed](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.plan](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.guardrails](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.guardrails_escalation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.plan_read_only](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_s3_bucket.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket.trail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket) | resource |
| [aws_s3_bucket_lifecycle_configuration.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_lifecycle_configuration.trail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_lifecycle_configuration) | resource |
| [aws_s3_bucket_ownership_controls.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_ownership_controls.trail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_ownership_controls) | resource |
| [aws_s3_bucket_policy.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_policy.trail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_policy) | resource |
| [aws_s3_bucket_public_access_block.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_public_access_block.trail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_public_access_block) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_server_side_encryption_configuration.trail](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_server_side_encryption_configuration) | resource |
| [aws_s3_bucket_versioning.state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket_versioning) | resource |
| [aws_sns_topic.notify](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic) | resource |
| [aws_sns_topic_policy.notify](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic_policy) | resource |
| [aws_sns_topic_subscription.notify_email](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic_subscription) | resource |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_iam_openid_connect_provider.github](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_openid_connect_provider) | data source |
| [aws_iam_policy_document.apply_state](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.deploy_base](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.guardrails](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.guardrails_escalation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.notify](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.plan](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.state_tls](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.trail_bucket](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.trust](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_iam_policy_document.workload_boundary](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| apply\_policy\_json | Composed permissions of the apply role, from the consumer root's apply-profile module (ADR 0002, T8). Null: the role has state access only. Checked structurally; the full lint is scripts/tf/policy.py. | `string` | `null` | no |
| create\_access\_analyzer | Create an IAM Access Analyzer external access analyzer for the account. | `bool` | `true` | no |
| create\_anomaly\_monitor | Create a Cost Anomaly Detection monitor and subscription (free). | `bool` | `true` | no |
| create\_oidc\_provider | Create the GitHub OIDC provider. Set false when the account already has one: an account holds a single GitHub provider, which is then looked up (ADR 0002, T2, F25). | `bool` | `true` | no |
| create\_trail | Create the multi-region CloudTrail trail and its bucket. Set false when the account already has a trail, so management events are not paid for twice. | `bool` | `true` | no |
| deploy\_policy\_json | Composed permissions of the deploy role, from the consumer root's deploy-profile module (T8). Null: the role has image push to the env repository only. | `string` | `null` | no |
| deploy\_profile\_name | Name of the deploy profile module the root wired into deploy\_policy\_json. It must equal platform.deploy\_role\_profile whenever deploy\_policy\_json is set (T8). | `string` | `null` | no |
| ecr\_repository\_policy\_json | Repository policy of the env ECR repository, from the runtime profile (for example the Lambda pull statement). Null: no repository policy. Promotion is deferred to Phase 2 (T6). | `string` | `null` | no |
| enable\_guardduty | Enable a GuardDuty detector. Off by default: free for 30 days, then billed by volume (ADR 0002, T7). The owner turns it on per account. | `bool` | `false` | no |
| env | Environment name (the key under envs in platform.yaml). | `string` | n/a | yes |
| github\_owner | GitHub user or organization that owns the consumer repository. | `string` | n/a | yes |
| github\_owner\_id | Immutable numeric ID of the GitHub owner. | `string` | n/a | yes |
| github\_repo | Consumer repository name. | `string` | n/a | yes |
| github\_repo\_id | Immutable numeric ID of the consumer repository. | `string` | n/a | yes |
| notification\_email | Address subscribed to the notify topic (budget, anomaly and OIDC alerts). Confirm the subscription once. | `string` | n/a | yes |
| platform | The env slice of the resolved plan (ADR 0002, M6 and M7): the validator's `--emit tfvars --env <e>` output, key `platform`. The slice is flat and carries more keys than the module reads (project, runtime, probes, built and so on); the type keeps only what it needs, and `env`, when present, must equal the `env` input. `prefix` is the project prefix; resources are named <prefix>-<env>. `roles` are names, never ARNs, and must equal <prefix>-<env>-gha-{plan,apply,deploy}. `observability.notify` is the SNS topic this module creates (M10). | ```object({ env = optional(string) tier = string prefix = string region = string deploy_role_profile = string budget_monthly_usd = number roles = object({ plan = string apply = string deploy = string }) observability = object({ notify = string }) })``` | n/a | yes |
| platform\_repository | owner/repo of the platform that hosts the reusable workflows the apply and deploy roles trust. | `string` | `"trungleviet-agilityio/sis-platform"` | no |
| trusted\_workflow\_shas | The workflow\_sha values the apply and deploy roles trust, N and N-1 (platform.lock trusted\_workflow\_shas; ADR 0002, L1, O9, O10). One or two distinct 40-hex commit SHAs. | `list(string)` | n/a | yes |

## Outputs

| Name | Description |
| ---- | ----------- |
| apply\_role\_arn | Role for apply jobs in this environment. |
| deploy\_role\_arn | Role for deploy jobs in this environment. |
| ecr\_repository\_arn | ECR repository ARN, for the profile modules. |
| ecr\_repository\_name | ECR repository of this environment. |
| notify\_topic\_arn | SNS topic for budget, anomaly and OIDC alerts. Confirm the email subscription once. |
| oidc\_provider\_arn | GitHub OIDC provider (created here or looked up). |
| oidc\_sub\_prefix | Subject prefix of every trust policy; must equal sub\_claim\_prefix reported by the GitHub OIDC API. |
| plan\_role\_arn | Role for plan jobs. |
| resource\_names | Name contract that profile and runtime modules follow. |
| state\_bucket\_name | Terraform state bucket (holds the account ID: never commit it). |
| trusted\_job\_workflow\_refs | job\_workflow\_ref values the apply and deploy roles trust (O9). Not secret: they hold the platform repository and SHAs. |
| workload\_boundary\_arn | Permissions boundary every workload role must carry (T11). Pass it to scripts/tf/policy.py --boundary-arn. |
<!-- END_TF_DOCS -->
