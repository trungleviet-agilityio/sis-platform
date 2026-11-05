# Credit: adapted from ship-it-safely infra/terraform/bootstrap/outputs.tf.
# Consumer roots must not print ARNs or the account ID in root outputs (public apply logs); these module outputs feed
# the profile modules and the owner's checkpoint steps.

output "state_bucket_name" {
  description = "Terraform state bucket (holds the account ID: never commit it)."
  value       = aws_s3_bucket.state.bucket
}

output "plan_role_arn" {
  description = "Role for plan jobs."
  value       = aws_iam_role.plan.arn
}

output "apply_role_arn" {
  description = "Role for apply jobs in this environment."
  value       = aws_iam_role.apply.arn
}

output "deploy_role_arn" {
  description = "Role for deploy jobs in this environment."
  value       = aws_iam_role.deploy.arn
}

output "oidc_provider_arn" {
  description = "GitHub OIDC provider (created here or looked up)."
  value       = local.oidc_provider_arn
}

output "workload_boundary_arn" {
  description = "Permissions boundary every workload role must carry (T11). Pass it to scripts/tf/policy.py --boundary-arn."
  value       = aws_iam_policy.workload_boundary.arn
}

output "ecr_repository_name" {
  description = "ECR repository of this environment."
  value       = aws_ecr_repository.app.name
}

output "ecr_repository_arn" {
  description = "ECR repository ARN, for the profile modules."
  value       = aws_ecr_repository.app.arn
}

output "notify_topic_arn" {
  description = "SNS topic for budget, anomaly and OIDC alerts. Confirm the email subscription once."
  value       = aws_sns_topic.notify.arn
}

output "trusted_job_workflow_refs" {
  description = "job_workflow_ref values the apply and deploy roles trust (O9). Not secret: they hold the platform repository and SHAs."
  value       = local.job_workflow_refs
}

output "oidc_sub_prefix" {
  description = "Subject prefix of every trust policy; must equal sub_claim_prefix reported by the GitHub OIDC API."
  value       = local.sub_base
}

output "resource_names" {
  description = "Name contract that profile and runtime modules follow."
  value       = local.resource_names
}
