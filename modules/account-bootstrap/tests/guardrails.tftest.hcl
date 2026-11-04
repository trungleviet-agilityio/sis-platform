# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/iam.tftest.hcl (guardrails, lab ADR 0007 S28).
# Guardrails G1 to G6 (ADR 0002, T4) are denies attached to all three roles, and the workload boundary (T11) is a
# ceiling with no IAM, STS or wildcard action.
mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{}" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:ap-southeast-1:123456789012:rule/sis-dev-oidc-unexpected" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:ap-southeast-1:123456789012:sis-dev-notify" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/sis-dev-workload-boundary" }
  }
}

variables {
  env = "dev"
  platform = {
    tier                = "nonprod"
    prefix              = "sis"
    region              = "ap-southeast-1"
    deploy_role_profile = "lambda-web"
    budget_monthly_usd  = 20
    roles = {
      plan   = "sis-dev-gha-plan"
      apply  = "sis-dev-gha-apply"
      deploy = "sis-dev-gha-deploy"
    }
    observability = { notify = "sis-dev-notify" }
  }
  github_owner          = "trungleviet-agilityio"
  github_repo           = "sis-platform-canary"
  github_owner_id       = "111"
  github_repo_id        = "222"
  trusted_workflow_shas = ["0123456789abcdef0123456789abcdef01234567"]
  notification_email    = "ops@example.com"
}

run "guardrails_are_attached_to_every_role" {
  command = plan

  assert {
    condition     = aws_iam_policy.guardrails.name == "sis-dev-gha-guardrails"
    error_message = "the guardrails policy is named <prefix>-<env>-gha-guardrails"
  }

  assert {
    condition     = toset(keys(aws_iam_role_policy_attachment.guardrails)) == toset(["plan", "apply", "deploy"])
    error_message = "guardrails must attach to the plan, apply and deploy roles"
  }
}

run "guardrails_deny_secrets_ssm_chaining_and_bootstrap" {
  command = plan

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.guardrails.statement : s.effect == "Deny"
    ])
    error_message = "guardrails hold Deny statements only"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement : (
        s.sid == "G1DenySecretValues"
        && contains(s.actions, "secretsmanager:GetSecretValue")
        && contains(s.actions, "secretsmanager:PutSecretValue")
        && contains(s.actions, "secretsmanager:BatchGetSecretValue")
      )
    ])
    error_message = "G1 must deny reading and writing secret values"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement :
      s.sid == "G2DenySsmParameterReads" && contains(s.actions, "ssm:GetParameter*")
    ])
    error_message = "G2 must deny SSM parameter reads"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement :
      s.sid == "G3DenyRoleChaining" && toset(s.actions) == toset(["sts:AssumeRole"])
    ])
    error_message = "G3 must deny role chaining"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement : (
        s.sid == "G4DenyBootstrapIamWrites"
        && contains(s.actions, "iam:Create*")
        && contains(s.actions, "iam:*PermissionsBoundary")
        && toset(s.resources) == toset([
          "arn:aws:iam::123456789012:role/sis-dev-gha-*",
          "arn:aws:iam::123456789012:policy/sis-dev-gha-*",
          "arn:aws:iam::123456789012:policy/sis-dev-workload-boundary",
          "arn:aws:iam::123456789012:oidc-provider/*",
        ])
      )
    ])
    error_message = "G4 must deny IAM writes on the gha roles and policies, the boundary and the OIDC provider"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement : (
        s.sid == "G5DenyBootstrapState"
        && toset(s.resources) == toset(["arn:aws:s3:::sis-dev-tfstate-123456789012-ap-southeast-1-an/bootstrap/*"])
      )
    ])
    error_message = "G5 must deny the bootstrap state key"
  }
}

run "guardrails_protect_audit_resources" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement :
      s.sid == "G6DenyAuditTrail" && toset(s.actions) == toset(["cloudtrail:*"])
    ])
    error_message = "G6 must deny cloudtrail:*"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement : (
        s.sid == "G6DenyAlertRule" && toset(s.actions) == toset(["events:*"])
        && toset(s.resources) == toset(["arn:aws:events:ap-southeast-1:123456789012:rule/sis-dev-oidc-unexpected"])
      )
    ])
    error_message = "G6 must deny events:* on the alert rule"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement : (
        s.sid == "G6DenyAlertTopic" && toset(s.actions) == toset(["sns:*"])
        && toset(s.resources) == toset(["arn:aws:sns:ap-southeast-1:123456789012:sis-dev-notify"])
      )
    ])
    error_message = "G6 must deny sns:* on the notify topic"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.guardrails.statement : (
        s.sid == "G6DenyTrailBucket" && toset(s.actions) == toset(["s3:*"])
        && toset(s.resources) == toset([
          "arn:aws:s3:::sis-dev-cloudtrail-123456789012-ap-southeast-1-an",
          "arn:aws:s3:::sis-dev-cloudtrail-123456789012-ap-southeast-1-an/*",
        ])
      )
    ])
    error_message = "G6 must deny s3:* on the trail bucket"
  }
}

run "boundary_is_a_runtime_neutral_ceiling" {
  command = plan

  assert {
    condition     = aws_iam_policy.workload_boundary.name == "sis-dev-workload-boundary"
    error_message = "the boundary is named <prefix>-<env>-workload-boundary"
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.workload_boundary.statement : (
        s.effect == "Allow"
        && alltrue([for a in s.actions : !startswith(a, "iam:") && !startswith(a, "sts:") && !strcontains(a, "*")])
      )
    ])
    error_message = "the boundary allows no IAM, STS or wildcard action"
  }

  assert {
    condition     = toset([for s in data.aws_iam_policy_document.workload_boundary.statement : s.sid]) == toset(["EcrAuth", "EcrPull", "LogsWrite", "AppSecretRead"])
    error_message = "the boundary holds ECR auth, ECR pull, logs write and the env secrets"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.workload_boundary.statement :
      s.sid == "AppSecretRead" && toset(s.resources) == toset(["arn:aws:secretsmanager:ap-southeast-1:123456789012:secret:sis/dev/*"])
    ])
    error_message = "the boundary reads only the secrets under <prefix>/<env>/"
  }

  assert {
    condition     = output.workload_boundary_arn == "arn:aws:iam::123456789012:policy/sis-dev-workload-boundary"
    error_message = "workload_boundary_arn must be an output"
  }
}
