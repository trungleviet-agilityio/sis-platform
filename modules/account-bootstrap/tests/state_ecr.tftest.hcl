# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/state.tftest.hcl (lab ADR 0002, B8, B9) and
# ship-it-serverless ecr tests.
# State bucket (ADR 0002, T3) and the ECR repository (T5).
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

run "bucket_identity" {
  command = plan

  assert {
    condition     = aws_s3_bucket.state.bucket == "sis-dev-tfstate-123456789012-ap-southeast-1-an"
    error_message = "bucket name must follow the account-regional pattern"
  }

  assert {
    condition     = aws_s3_bucket.state.bucket_namespace == "account-regional" && aws_s3_bucket.state.force_destroy == false
    error_message = "account-regional namespace and force_destroy false"
  }
}

run "bucket_hardening" {
  command = plan

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "versioning must be Enabled"
  }

  assert {
    condition = (
      one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
      && contains(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).blocked_encryption_types, "SSE-C")
    )
    error_message = "SSE-S3 with SSE-C blocked"
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.state.block_public_acls
      && aws_s3_bucket_public_access_block.state.block_public_policy
      && aws_s3_bucket_public_access_block.state.ignore_public_acls
      && aws_s3_bucket_public_access_block.state.restrict_public_buckets
    )
    error_message = "all four public access block flags must be true"
  }

  assert {
    condition     = one(aws_s3_bucket_ownership_controls.state.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "ownership must be BucketOwnerEnforced"
  }
}

run "tls_only_policy" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.state_tls.statement : (
        s.effect == "Deny"
        && contains(s.actions, "s3:*")
        && anytrue([
          for c in s.condition : c.test == "Bool" && c.variable == "aws:SecureTransport" && contains(c.values, "false")
        ])
      )
    ])
    error_message = "bucket policy must deny s3:* when aws:SecureTransport is false"
  }
}

run "state_lifecycle" {
  command = plan

  assert {
    condition = (
      one(one(aws_s3_bucket_lifecycle_configuration.state.rule).noncurrent_version_expiration).noncurrent_days == 90
      && one(one(aws_s3_bucket_lifecycle_configuration.state.rule).noncurrent_version_expiration).newer_noncurrent_versions == 10
      && one(one(aws_s3_bucket_lifecycle_configuration.state.rule).abort_incomplete_multipart_upload).days_after_initiation == 7
    )
    error_message = "noncurrent 90 days keeping 10, multipart abort after 7 days"
  }
}

run "ecr_repository_settings" {
  command = plan

  assert {
    condition = (
      aws_ecr_repository.app.name == "sis-dev-app"
      && aws_ecr_repository.app.image_tag_mutability == "IMMUTABLE"
      && aws_ecr_repository.app.image_scanning_configuration[0].scan_on_push
      && aws_ecr_repository.app.encryption_configuration[0].encryption_type == "AES256"
    )
    error_message = "one repository <prefix>-<env>-app, IMMUTABLE tags, scan on push, AES256"
  }
}

run "ecr_lifecycle_nonprod_keeps_20" {
  command = plan

  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].selection == { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 14 }
    error_message = "untagged images expire after 14 days"
  }

  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].rulePriority == 1 && jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[0].action.type == "expire"
    error_message = "rule 1 is the untagged expiry"
  }

  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[1].selection == { tagStatus = "tagged", tagPatternList = ["*"], countType = "imageCountMoreThan", countNumber = 20 }
    error_message = "nonprod keeps the newest 20 tagged images"
  }

  assert {
    condition     = length(jsondecode(aws_ecr_lifecycle_policy.app.policy).rules) == 2
    error_message = "exactly two lifecycle rules"
  }
}

run "ecr_lifecycle_prod_keeps_50" {
  command = plan

  variables {
    env = "prod"
    platform = {
      tier                = "prod"
      prefix              = "sis"
      region              = "ap-southeast-1"
      deploy_role_profile = "lambda-web"
      budget_monthly_usd  = 20
      roles = {
        plan   = "sis-prod-gha-plan"
        apply  = "sis-prod-gha-apply"
        deploy = "sis-prod-gha-deploy"
      }
      observability = { notify = "sis-prod-notify" }
    }
  }

  assert {
    condition     = aws_ecr_repository.app.name == "sis-prod-app"
    error_message = "the repository name follows the env"
  }

  assert {
    condition     = jsondecode(aws_ecr_lifecycle_policy.app.policy).rules[1].selection.countNumber == 50
    error_message = "prod keeps the newest 50 tagged images"
  }
}
