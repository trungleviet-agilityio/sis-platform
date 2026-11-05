# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/validation.tftest.hcl (lab ADR 0002, B5).
# Input validation (ADR 0002, T1, O4/O10): the trusted SHA list holds 1 or 2 distinct 40-hex values.
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

run "accepts_one_sha" {
  command = plan
}

run "accepts_two_shas" {
  command = plan

  variables {
    trusted_workflow_shas = [
      "0123456789abcdef0123456789abcdef01234567",
      "89abcdef0123456789abcdef0123456789abcdef",
    ]
  }
}

run "rejects_three_shas" {
  command = plan

  variables {
    trusted_workflow_shas = [
      "0123456789abcdef0123456789abcdef01234567",
      "89abcdef0123456789abcdef0123456789abcdef",
      "fedcba9876543210fedcba9876543210fedcba98",
    ]
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_an_empty_list" {
  command = plan

  variables {
    trusted_workflow_shas = []
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_a_non_hex_sha" {
  command = plan

  variables {
    trusted_workflow_shas = ["zzzz456789abcdef0123456789abcdef01234567"]
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_an_uppercase_sha" {
  command = plan

  variables {
    trusted_workflow_shas = ["0123456789ABCDEF0123456789ABCDEF01234567"]
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_a_short_sha" {
  command = plan

  variables {
    trusted_workflow_shas = ["0123456"]
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_a_tag_instead_of_a_sha" {
  command = plan

  variables {
    trusted_workflow_shas = ["v0.2.0"]
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_duplicate_shas" {
  command = plan

  variables {
    trusted_workflow_shas = [
      "0123456789abcdef0123456789abcdef01234567",
      "0123456789abcdef0123456789abcdef01234567",
    ]
  }

  expect_failures = [var.trusted_workflow_shas]
}

run "rejects_a_bad_env_name" {
  command = plan

  variables {
    env = "Dev"
  }

  expect_failures = [var.env]
}

run "rejects_a_one_character_env" {
  command = plan

  variables {
    env = "d"
  }

  expect_failures = [var.env]
}

run "rejects_an_env_with_a_path" {
  command = plan

  variables {
    env = "dev/../x"
  }

  expect_failures = [var.env]
}

run "rejects_an_unknown_tier" {
  command = plan

  variables {
    platform = {
      tier                = "staging"
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
  }

  expect_failures = [var.platform]
}

run "rejects_role_names_that_do_not_match_the_contract" {
  command = plan

  variables {
    platform = {
      tier                = "nonprod"
      prefix              = "sis"
      region              = "ap-southeast-1"
      deploy_role_profile = "lambda-web"
      budget_monthly_usd  = 20
      roles = {
        plan   = "sis-dev-plan"
        apply  = "sis-dev-gha-apply"
        deploy = "sis-dev-gha-deploy"
      }
      observability = { notify = "sis-dev-notify" }
    }
  }

  expect_failures = [var.platform]
}

run "rejects_a_zero_budget" {
  command = plan

  variables {
    platform = {
      tier                = "nonprod"
      prefix              = "sis"
      region              = "ap-southeast-1"
      deploy_role_profile = "lambda-web"
      budget_monthly_usd  = 0
      roles = {
        plan   = "sis-dev-gha-plan"
        apply  = "sis-dev-gha-apply"
        deploy = "sis-dev-gha-deploy"
      }
      observability = { notify = "sis-dev-notify" }
    }
  }

  expect_failures = [var.platform]
}

run "rejects_a_bad_region" {
  command = plan

  variables {
    platform = {
      tier                = "nonprod"
      prefix              = "sis"
      region              = "Singapore"
      deploy_role_profile = "lambda-web"
      budget_monthly_usd  = 20
      roles = {
        plan   = "sis-dev-gha-plan"
        apply  = "sis-dev-gha-apply"
        deploy = "sis-dev-gha-deploy"
      }
      observability = { notify = "sis-dev-notify" }
    }
  }

  expect_failures = [var.platform]
}

run "ignores_extra_plan_keys" {
  command = plan

  variables {
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
      observability = { notify = "sis-dev-notify", log_retention_days = 14 }
      account       = "dev"
      probes        = []
    }
  }
}

run "rejects_a_bad_email" {
  command = plan

  variables {
    notification_email = "not-an-email"
  }

  expect_failures = [var.notification_email]
}

run "rejects_non_numeric_owner_id" {
  command = plan

  variables {
    github_owner_id = "abc"
  }

  expect_failures = [var.github_owner_id]
}

run "rejects_non_numeric_repo_id" {
  command = plan

  variables {
    github_repo_id = "12x"
  }

  expect_failures = [var.github_repo_id]
}

run "rejects_a_bad_platform_repository" {
  command = plan

  variables {
    platform_repository = "no-slash"
  }

  expect_failures = [var.platform_repository]
}
