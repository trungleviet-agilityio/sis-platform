# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/iam.tftest.hcl (plan role, lab ADR 0007).
# Plan role (ADR 0002, T4, WA7): ReadOnlyAccess plus explicit denies on secret values, every KMS decrypt, S3 reads
# outside the state keys, and every action that is not a read, except the state lock object.
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

run "plan_role_is_read_only_access_plus_state" {
  command = plan

  assert {
    condition     = aws_iam_role_policy_attachment.plan_read_only.policy_arn == "arn:aws:iam::aws:policy/ReadOnlyAccess"
    error_message = "the plan role must carry the AWS managed ReadOnlyAccess policy"
  }

  assert {
    condition     = aws_iam_role_policy.plan.name == "state-access"
    error_message = "the plan role has an inline state-access policy"
  }

  assert {
    condition = toset([
      for s in data.aws_iam_policy_document.plan.statement : s.sid if s.effect == "Allow"
    ]) == toset(["StateList", "StateRead", "StateLock"])
    error_message = "the plan role allows only state listing, state read and the lock object"
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.plan.statement :
      alltrue([for a in s.actions : !strcontains(a, "*")]) if s.effect == "Allow"
    ])
    error_message = "no wildcard action in an Allow statement of the plan role"
  }
}

run "plan_role_denies_secret_values_and_kms_decrypt" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenySecretValueReads" && s.effect == "Deny"
        && toset(s.actions) == toset(["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"])
        && toset(s.resources) == toset(["*"])
      )
    ])
    error_message = "the plan role must deny reading secret values"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenyKmsDecrypt" && s.effect == "Deny"
        && toset(s.actions) == toset(["kms:Decrypt"])
        && toset(s.resources) == toset(["*"])
      )
    ])
    error_message = "the plan role must deny kms:Decrypt on every key"
  }
}

run "plan_role_denies_s3_reads_outside_state" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenyS3ReadsOutsideState" && s.effect == "Deny"
        && toset(s.actions) == toset(["s3:GetObject", "s3:GetObjectVersion"])
        && toset(s.not_resources) == toset([
          "arn:aws:s3:::sis-dev-tfstate-123456789012-ap-southeast-1-an/envs/dev/terraform.tfstate",
          "arn:aws:s3:::sis-dev-tfstate-123456789012-ap-southeast-1-an/envs/dev/terraform.tfstate.tflock",
        ])
      )
    ])
    error_message = "S3 object reads must be denied outside the state and lock keys"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "StateRead"
        && toset(s.resources) == toset(["arn:aws:s3:::sis-dev-tfstate-123456789012-ap-southeast-1-an/envs/dev/terraform.tfstate"])
      )
    ])
    error_message = "StateRead covers the env state key only (never bootstrap/)"
  }
}

run "plan_role_denies_every_non_read_action" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenyNonReadActions" && s.effect == "Deny"
        && toset(s.not_actions) == toset([
          "*:Get*", "*:List*", "*:Describe*", "*:Head*",
          "sts:GetCallerIdentity", "s3:PutObject", "s3:DeleteObject",
        ])
        && toset(s.resources) == toset(["*"])
      )
    ])
    error_message = "Deny NotAction must list exactly the read patterns, sts:GetCallerIdentity and the two lock actions"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenyS3WritesOutsideLock" && s.effect == "Deny"
        && toset(s.actions) == toset(["s3:PutObject", "s3:DeleteObject"])
        && toset(s.not_resources) == toset(["arn:aws:s3:::sis-dev-tfstate-123456789012-ap-southeast-1-an/envs/dev/terraform.tfstate.tflock"])
      )
    ])
    error_message = "s3:PutObject and s3:DeleteObject are allowed on the env .tflock key only"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "StateLock" && s.effect == "Allow"
        && toset(s.actions) == toset(["s3:GetObject", "s3:PutObject", "s3:DeleteObject"])
        && toset(s.resources) == toset(["arn:aws:s3:::sis-dev-tfstate-123456789012-ap-southeast-1-an/envs/dev/terraform.tfstate.tflock"])
      )
    ])
    error_message = "the lock object is the only place the plan role may write"
  }
}

run "plan_role_lists_only_the_state_prefixes" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "StateList"
        && toset(flatten([for c in s.condition : c.values if c.variable == "s3:prefix"])) == toset(["envs/dev/terraform.tfstate", "env:/*"])
      )
    ])
    error_message = "the backend may list the state key and the workspace prefix only"
  }
}
