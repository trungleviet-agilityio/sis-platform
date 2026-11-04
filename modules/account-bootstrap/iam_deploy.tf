# Credit: adapted from ship-it-serverless infra/terraform/bootstrap/iam_deploy.tf (lab ADR 0012 L9) and
# ship-it-safely iam_deploy.tf. The runtime specific release permissions (Lambda, ECS) come from the consumer root's
# deploy-profile module through deploy_policy_json (ADR 0002, T8). What stays here is runtime neutral: state access
# is not needed, image push to the one env repository is.
# O9: the trust names reusable-release.yml, which does not exist until Phase 2, so this role is inert by design.

resource "aws_iam_role" "deploy" {
  name                 = local.role_names.deploy
  description          = "GitHub Actions deploy: push one image, release through the deploy profile"
  path                 = "/"
  max_session_duration = 3600
  assume_role_policy   = data.aws_iam_policy_document.trust["deploy"].json

  lifecycle {
    # T8: the profile module the root wired must be the one the plan names (M6 deploy_role_profile).
    precondition {
      condition     = var.deploy_policy_json == null || var.deploy_profile_name == var.platform.deploy_role_profile
      error_message = "deploy_profile_name must equal platform.deploy_role_profile (the wired profile differs from the plan)."
    }
  }
}

data "aws_iam_policy_document" "deploy_base" {
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # No resource-level support
  }

  statement {
    sid    = "EcrPushOneRepo"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:DescribeImages",
    ]
    resources = [local.ecr_repo_app]
  }
}

resource "aws_iam_role_policy" "deploy_base" {
  name   = "image-push"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_base.json
}

resource "aws_iam_role_policy" "deploy_composed" {
  count = var.deploy_policy_json == null ? 0 : 1

  name   = "composed"
  role   = aws_iam_role.deploy.id
  policy = var.deploy_policy_json

  lifecycle {
    precondition {
      condition     = length(local.policy_violations.deploy) == 0
      error_message = "deploy_policy_json fails the structural check: ${join("; ", local.policy_violations.deploy)}"
    }
  }
}
