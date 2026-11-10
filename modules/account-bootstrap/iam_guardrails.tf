# Credit: adapted from ship-it-safely infra/terraform/bootstrap/iam_guardrails.tf (lab ADR 0007 S28, B16).
# T4: guardrails G1 to G8 attached to the plan, apply and deploy roles, and G9 (escalation) to apply and deploy.
# Action wildcards appear only in Deny statements. Two managed policies, because one is limited to 6144 characters.
# The owner's admin identity carries none of them, so the bootstrap apply is unaffected.
data "aws_iam_policy_document" "guardrails" {
  statement {
    sid    = "G1DenySecretValues"
    effect = "Deny"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:BatchGetSecretValue",
      "secretsmanager:PutSecretValue",
      "secretsmanager:UpdateSecretVersionStage",
      "secretsmanager:UpdateSecret",
      "secretsmanager:PutResourcePolicy",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "G2DenySsmParameterReads"
    effect    = "Deny"
    actions   = ["ssm:GetParameter*"] # Deny only: covers all four read APIs
    resources = ["*"]
  }

  statement {
    sid       = "G3DenyRoleChaining"
    effect    = "Deny"
    actions   = ["sts:AssumeRole"]
    resources = ["*"]
  }

  statement {
    sid    = "G4DenyBootstrapIamWrites"
    effect = "Deny"
    actions = [
      "iam:Create*",
      "iam:Put*",
      "iam:Update*",
      "iam:Delete*",
      "iam:Attach*",
      "iam:Detach*",
      "iam:Add*",
      "iam:Remove*",
      "iam:Tag*",
      "iam:Untag*",
      "iam:*PermissionsBoundary",
      "iam:*PolicyVersion",
      "iam:PassRole",
    ]
    resources = [
      "${local.iam_arn}:role/${local.name}-gha-*",
      "${local.iam_arn}:policy/${local.name}-gha-*",
      local.boundary_arn,
      "${local.iam_arn}:oidc-provider/*",
    ]
  }

  statement {
    sid       = "G5DenyBootstrapState"
    effect    = "Deny"
    actions   = ["s3:GetObject*", "s3:PutObject*", "s3:DeleteObject*"]
    resources = [local.bootstrap_arn]
  }

  # G7: the state bucket's own configuration and version history. The CI roles use the state keys only; changing the
  # bucket policy, versioning, lifecycle, encryption or public access block, or deleting versions, is the admin's job.
  statement {
    sid    = "G7DenyStateBucketAdmin"
    effect = "Deny"
    actions = [
      "s3:PutBucketPolicy",
      "s3:DeleteBucketPolicy",
      "s3:PutBucketVersioning",
      "s3:PutLifecycleConfiguration",
      "s3:DeleteBucket",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutEncryptionConfiguration",
      "s3:DeleteObjectVersion",
    ]
    resources = [local.bucket_arn, "${local.bucket_arn}/*"]
  }

  # G8: the app repository's policy, lifecycle and existence. The deploy role pushes images; nobody administers the
  # repository from CI.
  statement {
    sid    = "G8DenyEcrRepositoryAdmin"
    effect = "Deny"
    actions = [
      "ecr:SetRepositoryPolicy",
      "ecr:DeleteRepositoryPolicy",
      "ecr:DeleteRepository",
      "ecr:PutLifecyclePolicy",
      "ecr:DeleteLifecyclePolicy",
      "ecr:PutImageTagMutability",
    ]
    resources = [local.ecr_repo_app]
  }

  # G6: the audit trail, its bucket, the alert rule and the alert topic. No CI role needs any of them; this is
  # defense in depth against a future Allow. One statement per target, because a shared resource list would apply
  # every action to every resource.
  statement {
    sid       = "G6DenyAuditTrail"
    effect    = "Deny"
    actions   = ["cloudtrail:*"] # Deny only: widens protection
    resources = ["*"]
  }

  # The rest of the detective baseline and the cost alarms: nobody changes, disables or deletes them from CI.
  statement {
    sid    = "G6DenyDetectiveBaseline"
    effect = "Deny"
    actions = [
      "access-analyzer:Create*",
      "access-analyzer:Update*",
      "access-analyzer:Delete*",
      "guardduty:Create*",
      "guardduty:Update*",
      "guardduty:Delete*",
      "guardduty:Disable*",
      "guardduty:Disassociate*",
      "guardduty:Stop*",
      "budgets:Modify*",
      "budgets:Update*",
      "budgets:Delete*",
      "ce:UpdateAnomalyMonitor",
      "ce:DeleteAnomalyMonitor",
      "ce:UpdateAnomalySubscription",
      "ce:DeleteAnomalySubscription",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "G6DenyAlertRule"
    effect    = "Deny"
    actions   = ["events:*"] # Deny only: widens protection
    resources = concat([aws_cloudwatch_event_rule.oidc_unexpected.arn], aws_cloudwatch_event_rule.access_analyzer[*].arn)
  }

  statement {
    sid       = "G6DenyAlertTopic"
    effect    = "Deny"
    actions   = ["sns:*"] # Deny only: widens protection
    resources = [aws_sns_topic.notify.arn]
  }

  statement {
    sid       = "G6DenyTrailBucket"
    effect    = "Deny"
    actions   = ["s3:*"] # Deny only: widens protection
    resources = [local.trail_bucket_arn, "${local.trail_bucket_arn}/*"]
  }
}

# G9: the escalation rules of scripts/tf/policy.py, enforced in IAM. A role can only be created, given a policy or
# given a boundary with the workload boundary attached, the boundary can never be removed, and PassRole always names
# a service. StringNotEquals alone already matches a missing key; the Null statement states it. Attached to the apply
# and deploy roles only: the plan role cannot write IAM at all.
data "aws_iam_policy_document" "guardrails_escalation" {
  statement {
    sid    = "G9DenyRoleWritesWithOtherBoundary"
    effect = "Deny"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePolicy",
      "iam:AttachRolePolicy",
      "iam:PutRolePermissionsBoundary",
    ]
    resources = ["${local.iam_arn}:role/*"]

    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_arn]
    }
  }

  statement {
    sid    = "G9DenyRoleWritesWithoutBoundary"
    effect = "Deny"
    actions = [
      "iam:CreateRole",
      "iam:PutRolePolicy",
      "iam:AttachRolePolicy",
      "iam:PutRolePermissionsBoundary",
    ]
    resources = ["${local.iam_arn}:role/*"]

    condition {
      test     = "Null"
      variable = "iam:PermissionsBoundary"
      values   = ["true"]
    }
  }

  statement {
    sid       = "G9DenyDeleteRoleBoundary"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = ["*"]
  }

  statement {
    sid       = "G9DenyPassRoleWithoutService"
    effect    = "Deny"
    actions   = ["iam:PassRole"]
    resources = ["*"]

    condition {
      test     = "Null"
      variable = "iam:PassedToService"
      values   = ["true"]
    }
  }
}

resource "aws_iam_policy" "guardrails_escalation" {
  name        = "${local.name}-gha-escalation"
  description = "Escalation denies attached to the apply and deploy roles"
  policy      = data.aws_iam_policy_document.guardrails_escalation.json
}

resource "aws_iam_role_policy_attachment" "guardrails_escalation" {
  for_each = {
    apply  = aws_iam_role.apply.name
    deploy = aws_iam_role.deploy.name
  }

  role       = each.value
  policy_arn = aws_iam_policy.guardrails_escalation.arn
}

resource "aws_iam_policy" "guardrails" {
  name        = local.guardrails_name
  description = "Explicit denies attached to every GitHub Actions role"
  policy      = data.aws_iam_policy_document.guardrails.json
}

resource "aws_iam_role_policy_attachment" "guardrails" {
  for_each = {
    plan   = aws_iam_role.plan.name
    apply  = aws_iam_role.apply.name
    deploy = aws_iam_role.deploy.name
  }

  role       = each.value
  policy_arn = aws_iam_policy.guardrails.arn
}
