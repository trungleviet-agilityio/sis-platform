# OIDC provider (ADR 0002, T2): created by default with prevent_destroy and no thumbprint; a shared account looks the
# existing provider up instead (an account holds one GitHub provider, F25).
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
  mock_data "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
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

run "provider_is_created_by_default" {
  command = plan

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 1 && length(data.aws_iam_openid_connect_provider.github) == 0
    error_message = "the provider is created and not looked up by default"
  }

  assert {
    condition = (
      aws_iam_openid_connect_provider.github[0].url == "https://token.actions.githubusercontent.com"
      && aws_iam_openid_connect_provider.github[0].client_id_list == toset(["sts.amazonaws.com"])
    )
    error_message = "url and client id must be GitHub and sts.amazonaws.com"
  }
}

run "shared_account_uses_a_lookup" {
  command = plan

  variables {
    create_oidc_provider = false
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0 && length(data.aws_iam_openid_connect_provider.github) == 1
    error_message = "create_oidc_provider = false must look the provider up and create none"
  }

  assert {
    condition     = data.aws_iam_openid_connect_provider.github[0].url == "https://token.actions.githubusercontent.com"
    error_message = "the lookup is by the GitHub URL"
  }

  assert {
    condition = alltrue([
      for k, d in data.aws_iam_policy_document.trust : flatten([
        for p in d.statement[0].principals : p.identifiers
      ]) == ["arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"]
    ])
    error_message = "every trust policy must use the looked up provider ARN"
  }

  assert {
    condition     = output.oidc_provider_arn == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "the output returns the looked up provider ARN"
  }
}
