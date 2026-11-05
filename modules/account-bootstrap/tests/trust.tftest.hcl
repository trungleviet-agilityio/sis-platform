# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/trust.tftest.hcl (lab ADR 0007).
# OIDC trust (ADR 0002, O9, O14, T4): exact subjects with immutable IDs, ref pin on every role, the platform workflow
# file at each trusted SHA on apply and deploy only, and no pull request subject on the prod plan role.
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

run "nonprod_plan_trusts_pull_request" {
  command = plan

  assert {
    condition = flatten([
      for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.values
      if c.variable == "token.actions.githubusercontent.com:sub"
    ]) == ["repo:trungleviet-agilityio@111/sis-platform-canary@222:pull_request"]
    error_message = "the nonprod plan role sub must be the pull_request subject with immutable IDs"
  }

  assert {
    condition = [
      for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.test
      if c.variable == "token.actions.githubusercontent.com:ref"
      ] == ["StringLike"] && flatten([
        for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.values
        if c.variable == "token.actions.githubusercontent.com:ref"
    ]) == ["refs/pull/*/merge"]
    error_message = "the nonprod plan role ref must be StringLike refs/pull/*/merge (keeps pull_request_target out)"
  }

  assert {
    condition = length([
      for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c
      if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
    ]) == 0
    error_message = "the nonprod plan role pins no workflow file (O14)"
  }
}

run "apply_and_deploy_subjects_and_ref" {
  command = plan

  assert {
    condition = alltrue([
      for k in ["apply", "deploy"] : flatten([
        for c in data.aws_iam_policy_document.trust[k].statement[0].condition : c.values
        if c.variable == "token.actions.githubusercontent.com:sub"
      ]) == ["repo:trungleviet-agilityio@111/sis-platform-canary@222:environment:dev"]
    ])
    error_message = "apply and deploy subs must end with :environment:dev"
  }

  assert {
    condition = alltrue([
      for k in ["apply", "deploy"] : flatten([
        for c in data.aws_iam_policy_document.trust[k].statement[0].condition : c.values
        if c.variable == "token.actions.githubusercontent.com:ref"
      ]) == ["refs/heads/main"]
    ])
    error_message = "apply and deploy must pin ref to refs/heads/main"
  }
}

run "refs_are_built_per_role_file" {
  command = plan

  assert {
    condition = flatten([
      for c in data.aws_iam_policy_document.trust["apply"].statement[0].condition : c.values
      if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
    ]) == ["trungleviet-agilityio/sis-platform/.github/workflows/reusable-terraform-apply.yml@0123456789abcdef0123456789abcdef01234567"]
    error_message = "apply must trust reusable-terraform-apply.yml at the trusted SHA"
  }

  assert {
    condition = flatten([
      for c in data.aws_iam_policy_document.trust["deploy"].statement[0].condition : c.values
      if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
    ]) == ["trungleviet-agilityio/sis-platform/.github/workflows/reusable-release.yml@0123456789abcdef0123456789abcdef01234567"]
    error_message = "deploy must trust reusable-release.yml only, at the trusted SHA"
  }

  assert {
    condition = alltrue([
      for k in ["apply", "deploy"] : alltrue([
        for c in data.aws_iam_policy_document.trust[k].statement[0].condition : c.test == "StringEquals"
        if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
      ])
    ])
    error_message = "job_workflow_ref must use StringEquals, never StringLike"
  }
}

run "two_shas_give_two_refs_per_role" {
  command = plan

  variables {
    trusted_workflow_shas = [
      "0123456789abcdef0123456789abcdef01234567",
      "89abcdef0123456789abcdef0123456789abcdef",
    ]
  }

  assert {
    condition = flatten([
      for c in data.aws_iam_policy_document.trust["apply"].statement[0].condition : c.values
      if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
      ]) == [
      "trungleviet-agilityio/sis-platform/.github/workflows/reusable-terraform-apply.yml@0123456789abcdef0123456789abcdef01234567",
      "trungleviet-agilityio/sis-platform/.github/workflows/reusable-terraform-apply.yml@89abcdef0123456789abcdef0123456789abcdef",
    ]
    error_message = "apply must trust both N and N-1 workflow refs"
  }

  assert {
    condition = length(flatten([
      for c in data.aws_iam_policy_document.trust["deploy"].statement[0].condition : c.values
      if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
    ])) == 2
    error_message = "deploy must trust both N and N-1 workflow refs"
  }
}

run "platform_repository_is_configurable" {
  command = plan

  variables {
    platform_repository = "acme/platform-fork"
  }

  assert {
    condition = alltrue([
      for k in ["apply", "deploy"] : alltrue([
        for v in flatten([
          for c in data.aws_iam_policy_document.trust[k].statement[0].condition : c.values
          if c.variable == "token.actions.githubusercontent.com:job_workflow_ref"
        ]) : startswith(v, "acme/platform-fork/.github/workflows/")
      ])
    ])
    error_message = "job_workflow_ref must start with the platform repository"
  }
}

run "prod_plan_trusts_main_or_environment_only" {
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
    condition = flatten([
      for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.values
      if c.variable == "token.actions.githubusercontent.com:sub"
      ]) == [
      "repo:trungleviet-agilityio@111/sis-platform-canary@222:ref:refs/heads/main",
      "repo:trungleviet-agilityio@111/sis-platform-canary@222:environment:prod",
    ]
    error_message = "the prod plan role must trust only the main ref and the prod environment subjects"
  }

  assert {
    condition = !anytrue([
      for v in flatten([
        for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.values
      ]) : strcontains(v, "pull_request") || strcontains(v, "refs/pull/")
    ])
    error_message = "the prod plan role must have no pull_request sub and no pull request ref"
  }

  assert {
    condition = [
      for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.test
      if c.variable == "token.actions.githubusercontent.com:ref"
      ] == ["StringEquals"] && flatten([
        for c in data.aws_iam_policy_document.trust["plan"].statement[0].condition : c.values
        if c.variable == "token.actions.githubusercontent.com:ref"
    ]) == ["refs/heads/main"]
    error_message = "the prod plan role ref must be StringEquals refs/heads/main"
  }

  assert {
    condition = length(flatten([
      for k, d in data.aws_iam_policy_document.trust : [
        for c in d.statement[0].condition : c if c.test == "StringLike"
      ]
    ])) == 0
    error_message = "a prod account has no StringLike in any trust policy"
  }
}

run "conditions_are_exact" {
  command = plan

  assert {
    condition = length(flatten([
      for k, d in data.aws_iam_policy_document.trust : [
        for c in d.statement[0].condition : c if c.test == "StringLike"
      ]
    ])) == 1
    error_message = "exactly one StringLike is allowed across the nonprod trust policies"
  }

  assert {
    condition = alltrue([
      for k, d in data.aws_iam_policy_document.trust : flatten([
        for c in d.statement[0].condition : c.values
        if c.variable == "token.actions.githubusercontent.com:aud"
      ]) == ["sts.amazonaws.com"]
    ])
    error_message = "aud must be sts.amazonaws.com"
  }

  assert {
    condition = alltrue([
      for k, d in data.aws_iam_policy_document.trust : (
        flatten([for c in d.statement[0].condition : c.values if c.variable == "token.actions.githubusercontent.com:repository_id"]) == ["222"]
        && flatten([for c in d.statement[0].condition : c.values if c.variable == "token.actions.githubusercontent.com:repository_owner_id"]) == ["111"]
      )
    ])
    error_message = "repository_id and repository_owner_id must be pinned on every role"
  }

  assert {
    condition = alltrue([
      for k, d in data.aws_iam_policy_document.trust : flatten([
        for c in d.statement[0].condition : c.values
        if c.variable == "aws:RequestedRegion"
      ]) == ["ap-southeast-1"]
    ])
    error_message = "aws:RequestedRegion must be pinned to the env region on every role"
  }

  assert {
    condition = alltrue([
      for k, d in data.aws_iam_policy_document.trust :
      alltrue([for a in d.statement[0].actions : a == "sts:AssumeRoleWithWebIdentity"])
    ])
    error_message = "only sts:AssumeRoleWithWebIdentity may be allowed"
  }

  assert {
    condition = alltrue([
      for k, d in data.aws_iam_policy_document.trust : alltrue([
        for c in d.statement[0].condition : contains([
          "token.actions.githubusercontent.com:aud",
          "token.actions.githubusercontent.com:sub",
          "token.actions.githubusercontent.com:ref",
          "token.actions.githubusercontent.com:repository_id",
          "token.actions.githubusercontent.com:repository_owner_id",
          "token.actions.githubusercontent.com:job_workflow_ref",
          "aws:RequestedRegion",
        ], c.variable)
      ])
    ])
    error_message = "only documented condition keys may appear in a trust policy"
  }
}

run "roles_have_one_hour_sessions" {
  command = plan

  assert {
    condition = (
      aws_iam_role.plan.max_session_duration == 3600
      && aws_iam_role.apply.max_session_duration == 3600
      && aws_iam_role.deploy.max_session_duration == 3600
    )
    error_message = "every role has a 3600 second session"
  }

  assert {
    condition = (
      aws_iam_role.plan.name == "sis-dev-gha-plan"
      && aws_iam_role.apply.name == "sis-dev-gha-apply"
      && aws_iam_role.deploy.name == "sis-dev-gha-deploy"
    )
    error_message = "role names follow <prefix>-<env>-gha-<role>"
  }
}

run "oidc_subject_prefix_output" {
  command = plan

  assert {
    condition     = output.oidc_sub_prefix == "repo:trungleviet-agilityio@111/sis-platform-canary@222"
    error_message = "oidc_sub_prefix must carry the owner and repo IDs"
  }
}
