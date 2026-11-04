# Contract with the validator (ADR 0002, M6, M7). The `platform` value below is the output of
#   python3 intake/sis_intake/validate.py intake/examples/valid/ship-it-serverless.yaml --emit tfvars --env dev
# from sub-PR 1a (phase-1a-intake-contracts, commit d78f520), copied as it was printed. The module must accept the
# whole flat slice and read only the keys it needs. If 1a changes the shape, regenerate this value.
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
    format_version   = 1
    platform_version = "v0.2.0"
    schema_version   = 1
    env              = "dev"
    project = {
      name   = "ship-it-serverless"
      prefix = "sis"
      owner  = "trungleviet-agilityio"
    }
    runtime = {
      kind       = "lambda-web"
      family     = "lambda"
      arch       = "x86_64"
      front_door = "http-api"
    }
    workload = {
      port        = 8080
      health_path = "/health"
      peak_rps    = 50
      p95_ms      = 500
    }
    tier                = "nonprod"
    account             = "dev"
    region              = "ap-southeast-1"
    prefix              = "sis"
    delivery            = "push"
    promote_from        = null
    strategy            = "canary"
    steps               = [10, 100]
    bake_minutes        = 5
    probes              = ["/health", "/version"]
    rollback            = "alarm"
    engine              = "pipeline"
    deploy_role_profile = "lambda-alias"
    roles = {
      plan   = "sis-dev-gha-plan"
      apply  = "sis-dev-gha-apply"
      deploy = "sis-dev-gha-deploy"
    }
    budget_monthly_usd = 20
    data_class         = "internal"
    observability = {
      slo = {
        availability_pct = 99.0
        p95_ms           = 500
      }
      alarms = [
        "sis-dev-5xx-rate",
        "sis-dev-p95-latency",
        "sis-dev-throttles",
        "sis-dev-probe-failures",
      ]
      log_retention_days = 14
      notify             = "sis-dev-notify"
    }
    built = {
      runtime  = false
      engine   = false
      delivery = false
      profile  = false
    }
  }
  github_owner          = "trungleviet-agilityio"
  github_repo           = "sis-platform-canary"
  github_owner_id       = "111"
  github_repo_id        = "222"
  trusted_workflow_shas = ["0123456789abcdef0123456789abcdef01234567"]
  notification_email    = "ops@example.com"
}

run "emitted_slice_is_accepted_and_read" {
  command = plan

  assert {
    condition = (
      aws_iam_role.plan.name == "sis-dev-gha-plan"
      && aws_iam_role.apply.name == "sis-dev-gha-apply"
      && aws_iam_role.deploy.name == "sis-dev-gha-deploy"
      && aws_budgets_budget.monthly.limit_amount == "20"
      && aws_sns_topic.notify.name == "sis-dev-notify"
      && aws_s3_bucket.state.bucket == "sis-dev-tfstate-123456789012-ap-southeast-1-an"
    )
    error_message = "roles, budget, notify topic and bucket must come from the emitted slice"
  }
}

run "wired_profile_matches_the_emitted_profile_name" {
  command = plan

  variables {
    deploy_profile_name = "lambda-alias"
    deploy_policy_json  = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"lambda:PublishVersion\"],\"Resource\":\"arn:aws:lambda:ap-southeast-1:123456789012:function:sis-dev-app\"}]}"
  }

  assert {
    condition     = length(aws_iam_role_policy.deploy_composed) == 1
    error_message = "deploy_profile_name equal to deploy_role_profile must pass the precondition"
  }
}

run "a_slice_for_another_env_is_refused" {
  command = plan

  variables {
    env = "qa"
  }

  expect_failures = [var.platform]
}
