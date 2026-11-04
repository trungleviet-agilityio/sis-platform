# Credit: adapted from ship-it-safely infra/terraform/bootstrap/tests/{budget,monitoring}.tftest.hcl (lab ADR 0007).
# Budget and anomaly monitor (ADR 0002, T7, WA20) and the detective baseline: trail, Access Analyzer, GuardDuty flag,
# the notify topic and the OIDC alert rule (WA6).
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
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:ap-southeast-1:123456789012:sis-dev-notify" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:ap-southeast-1:123456789012:rule/sis-dev-oidc-unexpected" }
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

run "monthly_budget_from_the_plan" {
  command = plan

  assert {
    condition = (
      aws_budgets_budget.monthly.name == "sis-dev-monthly-cost"
      && aws_budgets_budget.monthly.budget_type == "COST"
      && aws_budgets_budget.monthly.limit_amount == "20"
      && aws_budgets_budget.monthly.limit_unit == "USD"
      && aws_budgets_budget.monthly.time_unit == "MONTHLY"
    )
    error_message = "a monthly COST budget of platform.budget_monthly_usd"
  }
}

run "budget_alerts_actual_and_forecast_at_80_and_100" {
  command = plan

  assert {
    condition = toset([
      for n in aws_budgets_budget.monthly.notification : "${n.notification_type}-${n.threshold}"
    ]) == toset(["ACTUAL-80", "ACTUAL-100", "FORECASTED-80", "FORECASTED-100"])
    error_message = "actual and forecast alerts at 80 and 100 percent"
  }

  assert {
    condition = alltrue([
      for n in aws_budgets_budget.monthly.notification :
      n.threshold_type == "PERCENTAGE" && n.comparison_operator == "GREATER_THAN"
      && n.subscriber_sns_topic_arns == toset(["arn:aws:sns:ap-southeast-1:123456789012:sis-dev-notify"])
    ])
    error_message = "every alert goes to the notify topic"
  }
}

run "budget_follows_the_plan_value" {
  command = plan

  variables {
    platform = {
      tier                = "nonprod"
      prefix              = "sis"
      region              = "ap-southeast-1"
      deploy_role_profile = "lambda-web"
      budget_monthly_usd  = 150
      roles = {
        plan   = "sis-dev-gha-plan"
        apply  = "sis-dev-gha-apply"
        deploy = "sis-dev-gha-deploy"
      }
      observability = { notify = "sis-dev-notify" }
    }
  }

  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "150"
    error_message = "the limit must follow platform.budget_monthly_usd"
  }
}

run "anomaly_monitor_is_on_by_default" {
  command = plan

  assert {
    condition     = length(aws_ce_anomaly_monitor.services) == 1 && length(aws_ce_anomaly_subscription.notify) == 1
    error_message = "the Cost Anomaly Detection monitor and subscription exist by default"
  }

  assert {
    condition = (
      aws_ce_anomaly_monitor.services[0].monitor_type == "DIMENSIONAL"
      && aws_ce_anomaly_monitor.services[0].monitor_dimension == "SERVICE"
      && aws_ce_anomaly_subscription.notify[0].frequency == "IMMEDIATE"
    )
    error_message = "a per-service monitor with immediate alerts"
  }

  assert {
    condition     = one(aws_ce_anomaly_subscription.notify[0].subscriber).type == "SNS" && one(aws_ce_anomaly_subscription.notify[0].subscriber).address == "arn:aws:sns:ap-southeast-1:123456789012:sis-dev-notify"
    error_message = "the subscriber is the notify topic"
  }
}

run "anomaly_monitor_can_be_turned_off" {
  command = plan

  variables {
    create_anomaly_monitor = false
  }

  assert {
    condition     = length(aws_ce_anomaly_monitor.services) == 0 && length(aws_ce_anomaly_subscription.notify) == 0
    error_message = "create_anomaly_monitor = false creates neither"
  }
}

run "trail_is_management_only_and_validated" {
  command = plan

  assert {
    condition = (
      length(aws_cloudtrail.this) == 1
      && aws_cloudtrail.this[0].name == "sis-dev-trail"
      && aws_cloudtrail.this[0].is_multi_region_trail
      && aws_cloudtrail.this[0].include_global_service_events
      && aws_cloudtrail.this[0].enable_log_file_validation
    )
    error_message = "a multi-region trail with log file validation exists by default"
  }

  assert {
    condition = (
      aws_cloudtrail.this[0].cloud_watch_logs_group_arn == null
      && aws_cloudtrail.this[0].kms_key_id == null
      && length(aws_cloudtrail.this[0].event_selector) == 0
      && length(aws_cloudtrail.this[0].advanced_event_selector) == 0
    )
    error_message = "management events only: no CloudWatch Logs, KMS or data events"
  }
}

run "trail_bucket_hardening_and_lifecycle" {
  command = plan

  assert {
    condition = (
      aws_s3_bucket.trail[0].bucket == "sis-dev-cloudtrail-123456789012-ap-southeast-1-an"
      && aws_s3_bucket.trail[0].bucket_namespace == "account-regional"
      && aws_s3_bucket_public_access_block.trail[0].block_public_acls
      && aws_s3_bucket_public_access_block.trail[0].block_public_policy
      && aws_s3_bucket_public_access_block.trail[0].ignore_public_acls
      && aws_s3_bucket_public_access_block.trail[0].restrict_public_buckets
      && one(aws_s3_bucket_ownership_controls.trail[0].rule).object_ownership == "BucketOwnerEnforced"
    )
    error_message = "the trail bucket is regional, private and owner enforced"
  }

  assert {
    condition = (
      one(aws_s3_bucket_server_side_encryption_configuration.trail[0].rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
      && contains(one(aws_s3_bucket_server_side_encryption_configuration.trail[0].rule).blocked_encryption_types, "SSE-C")
    )
    error_message = "SSE-S3 with SSE-C blocked"
  }

  assert {
    condition     = one(one(aws_s3_bucket_lifecycle_configuration.trail[0].rule).expiration).days == 30
    error_message = "trail logs expire after 30 days"
  }
}

run "trail_bucket_policy" {
  command = plan

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.trail_bucket.statement : (
        s.sid == "CloudTrailWrite"
        && toset(s.resources) == toset(["arn:aws:s3:::sis-dev-cloudtrail-123456789012-ap-southeast-1-an/AWSLogs/123456789012/*"])
        && anytrue([for c in s.condition : c.variable == "aws:SourceArn" && toset(c.values) == toset(["arn:aws:cloudtrail:ap-southeast-1:123456789012:trail/sis-dev-trail"])])
      )
    ])
    error_message = "CloudTrail writes only under its account prefix and only for this trail"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.trail_bucket.statement :
      s.sid == "DenyInsecureTransport" && s.effect == "Deny"
    ])
    error_message = "the trail bucket denies non-TLS access"
  }
}

run "existing_trail_is_respected" {
  command = plan

  variables {
    create_trail = false
  }

  assert {
    condition     = length(aws_cloudtrail.this) == 0 && length(aws_s3_bucket.trail) == 0
    error_message = "create_trail = false creates neither trail nor bucket"
  }

  assert {
    condition     = aws_cloudwatch_event_rule.oidc_unexpected.name == "sis-dev-oidc-unexpected"
    error_message = "the alert rule exists whether or not the module creates a trail"
  }
}

run "access_analyzer_on_and_guardduty_off_by_default" {
  command = plan

  assert {
    condition     = length(aws_accessanalyzer_analyzer.account) == 1 && aws_accessanalyzer_analyzer.account[0].type == "ACCOUNT"
    error_message = "an account external access analyzer exists by default"
  }

  assert {
    condition     = length(aws_guardduty_detector.this) == 0
    error_message = "GuardDuty is off by default (30-day trial then billed)"
  }
}

run "flags_switch_the_baseline" {
  command = plan

  variables {
    enable_guardduty       = true
    create_access_analyzer = false
  }

  assert {
    condition     = length(aws_guardduty_detector.this) == 1 && aws_guardduty_detector.this[0].enable
    error_message = "enable_guardduty = true creates an enabled detector"
  }

  assert {
    condition     = length(aws_accessanalyzer_analyzer.account) == 0
    error_message = "create_access_analyzer = false creates no analyzer"
  }
}

run "notify_topic_and_subscription" {
  command = plan

  assert {
    condition     = aws_sns_topic.notify.name == "sis-dev-notify"
    error_message = "the topic is named by platform.observability.notify (M10)"
  }

  assert {
    condition     = aws_sns_topic_subscription.notify_email.protocol == "email"
    error_message = "the subscription is email"
  }

  assert {
    condition     = toset([for s in data.aws_iam_policy_document.notify.statement : s.sid]) == toset(["EventBridgePublish", "BudgetsPublish", "CostAnomalyPublish"])
    error_message = "only EventBridge, Budgets and Cost Anomaly Detection may publish"
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.notify.statement : (
        s.effect == "Allow" && toset(s.actions) == toset(["sns:Publish"])
        && alltrue([for p in s.principals : p.type == "Service"])
      )
    ])
    error_message = "service principals with sns:Publish only"
  }

  assert {
    condition = anytrue([
      for s in data.aws_iam_policy_document.notify.statement : (
        s.sid == "EventBridgePublish"
        && anytrue([for c in s.condition : c.variable == "aws:SourceArn" && toset(c.values) == toset(["arn:aws:events:ap-southeast-1:123456789012:rule/sis-dev-oidc-unexpected"])])
      )
    ])
    error_message = "EventBridge publishes for the alert rule only"
  }

  assert {
    condition = alltrue([
      for s in data.aws_iam_policy_document.notify.statement :
      anytrue([for c in s.condition : c.variable == "aws:SourceAccount" || c.variable == "aws:SourceArn"])
    ])
    error_message = "every publisher is bound to this account or rule"
  }
}

run "alert_rule_pattern" {
  command = plan

  assert {
    condition     = aws_cloudwatch_event_rule.oidc_unexpected.state == "ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS"
    error_message = "the rule must opt in to read-only management events"
  }

  assert {
    condition = (
      jsondecode(aws_cloudwatch_event_rule.oidc_unexpected.event_pattern).source == ["aws.sts"]
      && jsondecode(aws_cloudwatch_event_rule.oidc_unexpected.event_pattern).detail.eventName == ["AssumeRoleWithWebIdentity"]
    )
    error_message = "the rule watches AssumeRoleWithWebIdentity"
  }

  assert {
    condition     = jsondecode(aws_cloudwatch_event_rule.oidc_unexpected.event_pattern).detail["$or"][0] == { errorCode = [{ exists = true }] }
    error_message = "a refusal (errorCode) alerts"
  }

  assert {
    condition = jsondecode(aws_cloudwatch_event_rule.oidc_unexpected.event_pattern).detail["$or"][1].userIdentity.userName[0]["anything-but"] == [
      "repo:trungleviet-agilityio@111/sis-platform-canary@222:environment:dev",
      "repo:trungleviet-agilityio@111/sis-platform-canary@222:pull_request",
    ]
    error_message = "a success for a subject outside the trust alerts"
  }
}
