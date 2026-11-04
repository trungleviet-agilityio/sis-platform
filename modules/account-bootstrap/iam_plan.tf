# Credit: adapted from ship-it-safely infra/terraform/bootstrap/iam_plan.tf (lab ADR 0002, B16, B17).
# T4, plan role (WA7): ReadOnlyAccess plus explicit denies. ReadOnlyAccess allows many Get* actions that expose
# data, so the denies close secret values, every KMS decrypt, S3 reads outside the state keys, and every action that
# is not a read. The one write a plan needs is the state lock object (s3:PutObject and s3:DeleteObject on the
# env's .tflock key). Missing reads surface in the A7 CloudTrail check.

resource "aws_iam_role" "plan" {
  name                 = local.role_names.plan
  description          = "GitHub Actions plan (read only)"
  path                 = "/"
  max_session_duration = 3600
  assume_role_policy   = data.aws_iam_policy_document.trust["plan"].json
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/ReadOnlyAccess"
}

data "aws_iam_policy_document" "plan" {
  statement {
    sid       = "StateList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = local.state_list_prefixes
    }
  }

  statement {
    sid       = "StateRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = [local.state_arn]
  }

  statement {
    sid       = "StateLock"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.lock_arn]
  }

  # ReadOnlyAccess grants s3:Get* on every bucket in the account; this closes it to the two state keys.
  statement {
    sid           = "DenyS3ReadsOutsideState"
    effect        = "Deny"
    actions       = ["s3:GetObject", "s3:GetObjectVersion"]
    not_resources = [local.state_arn, local.lock_arn]
  }

  statement {
    sid       = "DenySecretValueReads"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"]
    resources = ["*"]
  }

  # State is SSE-S3, so plan needs no key. This also blocks SecureString reads.
  statement {
    sid       = "DenyKmsDecrypt"
    effect    = "Deny"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
  }

  # Everything that is not a read is denied. Deny and NotAction together are safe: they widen the denial.
  # The read patterns use a wildcard service prefix (*:Get*) because IAM needs a prefix on every action. (C) Whether
  # IAM accepts a wildcard prefix is confirmed by the first bootstrap apply (it rejects a malformed policy up front).
  statement {
    sid    = "DenyNonReadActions"
    effect = "Deny"
    not_actions = [
      "*:Get*",
      "*:List*",
      "*:Describe*",
      "*:Head*",
      "sts:GetCallerIdentity",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["*"]
  }

  # The two S3 write actions above are allowed on the lock key only.
  statement {
    sid           = "DenyS3WritesOutsideLock"
    effect        = "Deny"
    actions       = ["s3:PutObject", "s3:DeleteObject"]
    not_resources = [local.lock_arn]
  }
}

resource "aws_iam_role_policy" "plan" {
  name   = "state-access"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan.json
}
