# Credit: adapted from ship-it-safely infra/terraform/bootstrap/iam_apply.tf (state access, lab ADR 0002 B18) and
# ship-it-serverless iam_apply.tf. The service permissions are not here: they come from the consumer root's
# apply-profile module through apply_policy_json (ADR 0002, T8), checked structurally below and fully by
# scripts/tf/policy.py (T11).

resource "aws_iam_role" "apply" {
  name                 = local.role_names.apply
  description          = "GitHub Actions apply for this environment's root, permissions composed from the apply profile"
  path                 = "/"
  max_session_duration = 3600
  assume_role_policy   = data.aws_iam_policy_document.trust["apply"].json
}

# State access only. Role permissions beyond it come from the composed policy.
data "aws_iam_policy_document" "apply_state" {
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
    sid       = "StateReadWrite"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = [local.state_arn]
  }

  statement {
    sid       = "StateLock"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [local.lock_arn]
  }
}

resource "aws_iam_role_policy" "apply_state" {
  name   = "state-access"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.apply_state.json
}

resource "aws_iam_role_policy" "apply_composed" {
  count = var.apply_policy_json == null ? 0 : 1

  name   = "composed"
  role   = aws_iam_role.apply.id
  policy = var.apply_policy_json

  lifecycle {
    precondition {
      condition     = length(local.policy_violations.apply) == 0
      error_message = "apply_policy_json fails the structural check: ${join("; ", local.policy_violations.apply)}"
    }
  }
}
