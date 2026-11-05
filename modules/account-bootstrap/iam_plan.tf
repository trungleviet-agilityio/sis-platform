# Credit: adapted from ship-it-safely infra/terraform/bootstrap/iam_plan.tf (lab ADR 0002, B16, B17).
# T4, plan role (WA7): the AWS managed ReadOnlyAccess policy plus explicit denies. ReadOnlyAccess is not purely
# read-only (v191 grants sqs:Receive*, s3express:CreateSession, dynamodb:PartiQLSelect, logs:StartQuery and
# StartLiveTail, cognito-idp:AdminGet*, codecommit:GitPull, eks:AccessKubernetesApi, config:Deliver* and many
# data-plane reads), so the denies below close secret values, SSM parameter reads, every KMS decrypt, the data
# plane actions of the services a project can hold data in, and S3 object reads outside the state keys. The only
# write the role is given is the inline StateLock statement on the env's .tflock key. Accepted (O14): reads the
# list does not name stay readable by a same-repo PR author in nonprod, and the nonprod plan role can write the
# lock object (lock interference). Missing reads surface in the A7 CloudTrail check.

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
    actions       = ["s3:GetObject*"]
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

  statement {
    sid       = "DenySsmParameterReads"
    effect    = "Deny"
    actions   = ["ssm:GetParameter*"] # Deny only: covers all four read APIs, including SecureString values
    resources = ["*"]
  }

  # Data plane reads that ReadOnlyAccess grants. Deny only; wildcards stay in the action name.
  statement {
    sid    = "DenyDataPlaneReads"
    effect = "Deny"
    actions = [
      "athena:GetQueryResults*",
      "codecommit:GitPull",
      "cognito-idp:AdminGet*",
      "config:Deliver*",
      "dynamodb:BatchGetItem",
      "dynamodb:GetItem",
      "dynamodb:PartiQLSelect",
      "dynamodb:Query",
      "dynamodb:Scan",
      "eks:AccessKubernetesApi",
      "kinesis:GetRecords",
      "kinesis:GetShardIterator",
      "logs:FilterLogEvents",
      "logs:GetLogEvents",
      "logs:GetQueryResults",
      "logs:StartLiveTail",
      "logs:StartQuery",
      "s3express:CreateSession",
      "sqs:Receive*",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "plan" {
  name   = "state-access"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan.json
}
