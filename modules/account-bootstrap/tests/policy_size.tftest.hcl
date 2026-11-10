# Policy size (AWS IAM quotas): a managed policy holds at most 6144 characters (white space not counted) and the
# inline policies of one role at most 10240 in total. The mock cannot render `.json`, so each document is
# measured as compact JSON of its `statement` attribute. That form carries empty fields (null lists, empty
# conditions) that the real document omits, so the measure is an upper bound of the real size; a document
# under the limit here is under it for real.
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

run "managed_policies_stay_under_6144_characters" {
  command = plan

  assert {
    condition     = length(jsonencode(data.aws_iam_policy_document.guardrails.statement)) < 6144
    error_message = "guardrails is ${length(jsonencode(data.aws_iam_policy_document.guardrails.statement))} characters (limit 6144): split it"
  }

  assert {
    condition     = length(jsonencode(data.aws_iam_policy_document.guardrails_escalation.statement)) < 6144
    error_message = "guardrails_escalation is ${length(jsonencode(data.aws_iam_policy_document.guardrails_escalation.statement))} characters (limit 6144)"
  }

  assert {
    condition     = length(jsonencode(data.aws_iam_policy_document.workload_boundary.statement)) < 6144
    error_message = "workload_boundary is ${length(jsonencode(data.aws_iam_policy_document.workload_boundary.statement))} characters (limit 6144)"
  }
}

run "inline_policies_of_a_role_stay_under_10240_characters" {
  command = plan

  assert {
    condition     = length(jsonencode(data.aws_iam_policy_document.plan.statement)) < 10240
    error_message = "the plan role inline policy is ${length(jsonencode(data.aws_iam_policy_document.plan.statement))} characters (limit 10240)"
  }

  assert {
    condition = (
      length(jsonencode(data.aws_iam_policy_document.apply_state.statement))
      + length(jsonencode(data.aws_iam_policy_document.deploy_base.statement)) < 10240
    )
    error_message = "the apply state policy and the deploy base policy are each far under 10240"
  }
}
