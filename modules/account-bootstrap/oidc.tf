# Credit: adapted from ship-it-safely and ship-it-serverless infra/terraform/bootstrap/oidc.tf (lab ADR 0007).

# T2: one provider per account (F25). No thumbprint_list: AWS validates GitHub's TLS chain against its own trusted
# CAs. prevent_destroy: removing the provider locks every pipeline out of the account.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://${local.oidc_host}"
  client_id_list = ["sts.amazonaws.com"]

  lifecycle {
    prevent_destroy = true
  }
}

# One trust policy per role: StringEquals except the nonprod plan role's pull request merge ref, immutable IDs,
# ref pinned on every role, and the platform workflow file at each trusted SHA (job_workflow_ref) on apply and deploy.
data "aws_iam_policy_document" "trust" {
  for_each = local.trust

  statement {
    sid     = "GitHubOidc"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = each.value.subs
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:repository_id"
      values   = [var.github_repo_id]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:repository_owner_id"
      values   = [var.github_owner_id]
    }

    condition {
      test     = each.value.ref_test
      variable = "${local.oidc_host}:ref"
      values   = [each.value.ref]
    }

    # The alert rule only sees this region's events. aws:RequestedRegion is always in the request context, and calls
    # to the global STS endpoint carry us-east-1, so those are refused too.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = [local.region]
    }

    dynamic "condition" {
      for_each = length(each.value.workflows) == 0 ? [] : [each.value.workflows]

      content {
        test     = "StringEquals"
        variable = "${local.oidc_host}:job_workflow_ref"
        values   = condition.value
      }
    }
  }
}
