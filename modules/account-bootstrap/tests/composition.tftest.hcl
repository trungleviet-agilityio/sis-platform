# Composition (ADR 0002, T8): apply and deploy permissions arrive as policy JSON from the consumer root. The module
# keeps only cheap structural checks (no Allow with * or iam:* actions, no NotAction, no NotResource, in string and
# list form) and the profile-name check; scripts/tf/policy.py does the full lint (T11).
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

run "no_composed_policy_by_default" {
  command = plan

  assert {
    condition     = length(aws_iam_role_policy.apply_composed) == 0 && length(aws_iam_role_policy.deploy_composed) == 0
    error_message = "without apply_policy_json and deploy_policy_json no composed policy exists"
  }

  assert {
    condition     = length(aws_ecr_repository_policy.app) == 0
    error_message = "without ecr_repository_policy_json no repository policy exists"
  }
}

run "valid_policies_are_attached_in_list_form" {
  command = plan

  variables {
    deploy_profile_name = "lambda-web"
    apply_policy_json   = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\"],\"Resource\":\"arn:aws:s3:::example-bucket/*\"}]}"
    deploy_policy_json  = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"lambda:UpdateFunctionCode\"],\"Resource\":\"*\"}]}"
  }

  assert {
    condition     = length(aws_iam_role_policy.apply_composed) == 1 && length(aws_iam_role_policy.deploy_composed) == 1
    error_message = "both composed policies must be attached"
  }
}

run "valid_policies_are_attached_in_string_form" {
  command = plan

  variables {
    deploy_profile_name = "lambda-web"
    apply_policy_json   = "{\"Version\":\"2012-10-17\",\"Statement\":{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"Resource\":\"arn:aws:s3:::example-bucket/*\"}}"
  }

  assert {
    condition     = length(aws_iam_role_policy.apply_composed) == 1
    error_message = "a single statement object with a string action is a valid policy"
  }
}

run "apply_rejects_star_action_string" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"*\",\"Resource\":\"*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_star_action_in_list" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"*\"],\"Resource\":\"*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_iam_star_in_object_statement" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":{\"Effect\":\"Allow\",\"Action\":[\"iam:*\"],\"Resource\":\"*\"}}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_not_action_string" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"NotAction\":\"iam:*\",\"Resource\":\"*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_not_action_list" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"NotAction\":[\"iam:*\",\"sts:*\"],\"Resource\":\"*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_not_resource_string" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:GetObject\",\"NotResource\":\"arn:aws:s3:::example-bucket/*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_not_resource_list" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\"],\"NotResource\":[\"arn:aws:s3:::example-bucket/*\"]}]}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "apply_rejects_a_document_without_statement" {
  command = plan

  variables {
    apply_policy_json = "{\"Version\":\"2012-10-17\"}"
  }

  expect_failures = [aws_iam_role_policy.apply_composed]
}

run "deploy_rejects_star_action" {
  command = plan

  variables {
    deploy_profile_name = "lambda-web"
    deploy_policy_json  = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"*\"],\"Resource\":\"*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.deploy_composed]
}

run "deploy_rejects_not_action_and_not_resource" {
  command = plan

  variables {
    deploy_profile_name = "lambda-web"
    deploy_policy_json  = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"NotAction\":\"iam:*\",\"NotResource\":\"*\"}]}"
  }

  expect_failures = [aws_iam_role_policy.deploy_composed]
}

run "profile_name_must_match_the_plan" {
  command = plan

  variables {
    deploy_profile_name = "ecs-fargate"
    deploy_policy_json  = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"lambda:UpdateFunctionCode\"],\"Resource\":\"arn:aws:lambda:ap-southeast-1:123456789012:function:sis-dev-app\"}]}"
  }

  expect_failures = [aws_iam_role.deploy]
}

run "missing_profile_name_is_refused_when_a_deploy_policy_is_wired" {
  command = plan

  variables {
    deploy_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"lambda:UpdateFunctionCode\"],\"Resource\":\"arn:aws:lambda:ap-southeast-1:123456789012:function:sis-dev-app\"}]}"
  }

  expect_failures = [aws_iam_role.deploy]
}

run "deploy_base_pushes_to_the_one_repository" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.deploy_base.statement : (
        s.sid == "EcrPushOneRepo"
        && toset(s.resources) == toset(["arn:aws:ecr:ap-southeast-1:123456789012:repository/sis-dev-app"])
      )
    ])
    error_message = "image push is scoped to the one env repository"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.deploy_base.statement :
      s.sid == "EcrAuth" && toset(s.actions) == toset(["ecr:GetAuthorizationToken"])
    ])
    error_message = "the authorization token is the only action on Resource *"
  }

  assert {
    condition = !anytrue([
      for s in data.aws_iam_policy_document.deploy_base.statement :
      anytrue([for a in s.actions : a == "ecr:SetRepositoryPolicy"])
    ])
    error_message = "no CI role may set the repository policy"
  }
}

run "repository_policy_comes_from_the_profile" {
  command = plan

  variables {
    ecr_repository_policy_json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
  }

  assert {
    condition     = length(aws_ecr_repository_policy.app) == 1
    error_message = "a supplied repository policy must be attached"
  }
}
