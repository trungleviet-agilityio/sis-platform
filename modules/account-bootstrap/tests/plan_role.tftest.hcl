# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/iam.tftest.hcl (plan role, lab ADR 0007).
# Plan role (ADR 0002, T4, WA7): ReadOnlyAccess plus explicit denies on secret values, SSM parameter reads, every KMS
# decrypt and S3 reads outside the state keys. The only write is the state lock object.
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
        && toset(s.actions) == toset(["s3:GetObject*"])
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

run "plan_role_writes_only_the_lock_object" {
  command = plan

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

  assert {
    condition = toset([
      for s in data.aws_iam_policy_document.plan.statement : s.sid
      if s.effect == "Allow" && anytrue([for a in s.actions : contains(["s3:PutObject", "s3:DeleteObject"], a)])
    ]) == toset(["StateLock"])
    error_message = "no other Allow grants a write"
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.plan.statement : try(length(s.not_actions), 0) == 0
    ])
    error_message = "no NotAction anywhere in the plan role policy (IAM wildcards are valid in the action name only)"
  }

  assert {
    condition = toset([
      for s in data.aws_iam_policy_document.plan.statement : s.sid if s.effect == "Deny"
    ]) == toset(["DenyS3ReadsOutsideState", "DenySecretValueReads", "DenyKmsDecrypt", "DenySsmParameterReads", "DenyDataPlaneReads"])
    error_message = "the explicit denies are secrets, SSM parameter reads, KMS decrypt, data plane reads and S3 reads outside the state keys"
  }
}

run "plan_role_denies_the_data_plane_reads_of_read_only_access" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenyDataPlaneReads" && s.effect == "Deny"
        && toset(s.resources) == toset(["*"])
        && toset(s.actions) == toset([
          "athena:GetQueryResults*", "codecommit:GitPull", "cognito-idp:AdminGet*", "config:Deliver*",
          "dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:PartiQLSelect", "dynamodb:Query", "dynamodb:Scan",
          "eks:AccessKubernetesApi", "kinesis:GetRecords", "kinesis:GetShardIterator",
          "logs:FilterLogEvents", "logs:GetLogEvents", "logs:GetQueryResults", "logs:StartLiveTail", "logs:StartQuery",
          "s3express:CreateSession", "sqs:Receive*",
        ])
      )
    ])
    error_message = "the plan role must deny the data plane actions that ReadOnlyAccess grants"
  }
}

run "plan_role_denies_ssm_parameter_reads" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.plan.statement : (
        s.sid == "DenySsmParameterReads" && s.effect == "Deny"
        && toset(s.actions) == toset(["ssm:GetParameter*"])
        && toset(s.resources) == toset(["*"])
      )
    ])
    error_message = "the plan role must deny SSM parameter reads (SecureString values)"
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
