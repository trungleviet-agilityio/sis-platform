# Credit: adapted from ship-it-safely infra/terraform/bootstrap/monitoring.tf (lab ADR 0007 S8, S22 to S27).
# T7, detective baseline (WA6): a multi-region management-event trail, an IAM Access Analyzer, an optional GuardDuty
# detector, and an EventBridge rule that mails the notify topic when a GitHub OIDC assumption is refused or granted
# to an unexpected subject. About 0 USD a month: the first trail copy of management events is free, EventBridge
# ingests management events for free, and there is no CloudWatch Logs delivery, KMS key or CloudTrail role.
# When org-baseline adds an organization trail, the account trail is removed (accepted).

locals {
  trail_name        = "${local.name}-trail"
  trail_bucket_name = "${local.name}-cloudtrail-${local.account_id}-${local.region}-an"
  trail_bucket_arn  = "arn:${local.partition}:s3:::${local.trail_bucket_name}"
  # Built from names, not from aws_cloudtrail.this: the bucket policy must exist before the trail can be created.
  trail_arn = "arn:${local.partition}:cloudtrail:${local.region}:${local.account_id}:trail/${local.trail_name}"
  rule_name = "${local.name}-oidc-unexpected"

  # The subjects a healthy pipeline presents. They hold owner and repo IDs, never the account ID.
  expected_subs = distinct(flatten([for t in local.trust : t.subs]))
}

# Trail bucket

resource "aws_s3_bucket" "trail" {
  count = var.create_trail ? 1 : 0

  bucket = local.trail_bucket_name
  # Only this account can create names in its account-regional namespace.
  bucket_namespace = "account-regional"
  # Teardown in one step; the lifecycle below expires the logs anyway.
  force_destroy = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  count = var.create_trail ? 1 : 0

  bucket = aws_s3_bucket.trail[0].id

  rule {
    blocked_encryption_types = ["SSE-C"]

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "trail" {
  count = var.create_trail ? 1 : 0

  bucket = aws_s3_bucket.trail[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "trail" {
  count = var.create_trail ? 1 : 0

  bucket = aws_s3_bucket.trail[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  count = var.create_trail ? 1 : 0

  bucket = aws_s3_bucket.trail[0].id

  rule {
    id     = "expire-trail-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"] # Deny only: widens protection
    resources = [local.trail_bucket_arn, "${local.trail_bucket_arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "CloudTrailAclCheck"
    effect    = "Allow"
    actions   = ["s3:GetBucketAcl"]
    resources = [local.trail_bucket_arn]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }

  statement {
    sid       = "CloudTrailWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${local.trail_bucket_arn}/AWSLogs/${local.account_id}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = [local.trail_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  count = var.create_trail ? 1 : 0

  bucket = aws_s3_bucket.trail[0].id
  policy = data.aws_iam_policy_document.trail_bucket.json

  depends_on = [aws_s3_bucket_public_access_block.trail]
}

# Management events only: no CloudWatch Logs, no KMS, no data events. Skipped when the account already has a trail.
resource "aws_cloudtrail" "this" {
  count = var.create_trail ? 1 : 0

  name                          = local.trail_name
  s3_bucket_name                = aws_s3_bucket.trail[0].id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true

  depends_on = [aws_s3_bucket_policy.trail]
}

# Access Analyzer (external access, account zone of trust) and GuardDuty (opt in).

resource "aws_accessanalyzer_analyzer" "account" {
  count = var.create_access_analyzer ? 1 : 0

  analyzer_name = "${local.name}-external-access"
  type          = "ACCOUNT"
}

resource "aws_guardduty_detector" "this" {
  count = var.enable_guardduty ? 1 : 0

  enable = true
}

# Access Analyzer findings (external access to a role, bucket, key and so on) go to the notify topic as they appear.
resource "aws_cloudwatch_event_rule" "access_analyzer" {
  count = var.create_access_analyzer ? 1 : 0

  name        = "${local.name}-access-analyzer-finding"
  description = "IAM Access Analyzer reported a finding"

  event_pattern = jsonencode({
    source        = ["aws.access-analyzer"]
    "detail-type" = ["Access Analyzer Finding"]
    detail        = { status = ["ACTIVE"] }
  })
}

resource "aws_cloudwatch_event_target" "access_analyzer" {
  count = var.create_access_analyzer ? 1 : 0

  rule = aws_cloudwatch_event_rule.access_analyzer[0].name
  arn  = aws_sns_topic.notify.arn

  input_transformer {
    input_paths = {
      resource = "$.detail.resource"
      type     = "$.detail.resourceType"
      public   = "$.detail.isPublic"
      time     = "$.time"
    }
    input_template = <<-EOT
      "IAM Access Analyzer finding from rule <aws.events.rule-name>: a resource can be reached from outside this account."
      "Resource: <resource> (<type>)"
      "Public: <public>"
      "Time: <time>"
      "Details: IAM Access Analyzer console, active findings."
    EOT
  }
}

# Notify topic (M10) and alert rule

# No KMS: EventBridge cannot publish to a topic that uses the AWS-managed SNS key, and a CMK costs money.
resource "aws_sns_topic" "notify" {
  name = var.platform.observability.notify
}

data "aws_iam_policy_document" "notify" {
  statement {
    sid       = "EventBridgePublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = concat([aws_cloudwatch_event_rule.oidc_unexpected.arn], aws_cloudwatch_event_rule.access_analyzer[*].arn)
    }
  }

  statement {
    sid       = "BudgetsPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:budgets::${local.account_id}:*"]
    }
  }

  statement {
    sid       = "CostAnomalyPublish"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notify.arn]

    principals {
      type        = "Service"
      identifiers = ["costalerts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "notify" {
  arn    = aws_sns_topic.notify.arn
  policy = data.aws_iam_policy_document.notify.json
}

# The recipient confirms the subscription by email once.
resource "aws_sns_topic_subscription" "notify_email" {
  topic_arn = aws_sns_topic.notify.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# AssumeRoleWithWebIdentity is logged as a read-only event, so the rule must opt in to read-only management
# events. A refusal alerts through errorCode; a success with a subject outside the trust alerts through
# anything-but.
resource "aws_cloudwatch_event_rule" "oidc_unexpected" {
  name        = local.rule_name
  description = "GitHub OIDC assumption refused, or granted to an unexpected subject"
  state       = "ENABLED_WITH_ALL_CLOUDTRAIL_MANAGEMENT_EVENTS"

  event_pattern = jsonencode({
    source        = ["aws.sts"]
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventName = ["AssumeRoleWithWebIdentity"]
      "$or" = [
        { errorCode = [{ exists = true }] },
        { userIdentity = { userName = [{ "anything-but" = local.expected_subs }] } },
      ]
    }
  })
}

# A few plain lines instead of the raw event JSON; the full event stays in CloudTrail. Each line is its own quoted
# string, which is how EventBridge emits multi-line text. A path missing from the event (errorCode on a success)
# creates no variable, so that line ends blank.
resource "aws_cloudwatch_event_target" "notify" {
  rule = aws_cloudwatch_event_rule.oidc_unexpected.name
  arn  = aws_sns_topic.notify.arn

  input_transformer {
    input_paths = {
      time    = "$.detail.eventTime"
      region  = "$.detail.awsRegion"
      sub     = "$.detail.userIdentity.userName"
      role    = "$.detail.requestParameters.roleArn"
      session = "$.detail.requestParameters.roleSessionName"
      error   = "$.detail.errorCode"
      ip      = "$.detail.sourceIPAddress"
    }
    input_template = <<-EOT
      "GitHub OIDC alert from rule <aws.events.rule-name>: an AssumeRoleWithWebIdentity call was refused, or granted to a subject outside the trust."
      "Time: <time> (<region>)"
      "Error code (blank: the role was granted, check the trust): <error>"
      "Role: <role>"
      "Subject (sub): <sub>"
      "Session: <session>"
      "Source IP: <ip>"
      "Full event: CloudTrail event history, event name AssumeRoleWithWebIdentity."
    EOT
  }
}
