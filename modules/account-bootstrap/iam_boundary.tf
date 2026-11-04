# Credit: adapted from ship-it-safely infra/terraform/bootstrap/iam_ecs_boundary.tf and ship-it-serverless
# iam_app_boundary.tf (lab ADR 0002 B15, ADR 0012 L9).
# T11: the permissions boundary every workload role (Lambda execution role, ECS task and execution role) must carry.
# Owned by bootstrap, so no GitHub role can edit it (guardrail G4). The apply profile may create or change a role
# only with iam:PermissionsBoundary equal to this ARN (scripts/tf/policy.py enforces that in the policy it composes).
# The ceiling is runtime neutral: logs of this env's functions and services, image pull from this env's
# repositories, and the env's secrets. A role's own policy is narrower; the boundary holds even if it were widened.
data "aws_iam_policy_document" "workload_boundary" {
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # No resource-level support
  }

  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = [local.ecr_repo_env]
  }

  statement {
    sid     = "LogsWrite"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${local.svc_arn["logs"]}:log-group:/aws/lambda/${local.name}-*:*",
      "${local.svc_arn["logs"]}:log-group:/ecs/${local.name}-*:*",
    ]
  }

  statement {
    sid       = "AppSecretRead"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.secret_pattern]
  }
}

resource "aws_iam_policy" "workload_boundary" {
  name        = local.resource_names.boundary
  description = "Permissions boundary required on every workload role of this environment"
  policy      = data.aws_iam_policy_document.workload_boundary.json
}
