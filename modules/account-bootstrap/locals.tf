# Credit: adapted from ship-it-safely and ship-it-serverless infra/terraform/bootstrap/locals.tf (lab ADR 0002,
# ADR 0007 S2, ADR 0012 L3).
locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = var.platform.region
  name       = "${var.platform.prefix}-${var.env}"
  is_prod    = var.platform.tier == "prod"

  # State bucket (T3) and the only keys the CI roles may touch.
  bucket_name   = "${local.name}-tfstate-${local.account_id}-${local.region}-an"
  bucket_arn    = "arn:${local.partition}:s3:::${local.bucket_name}"
  state_key     = "envs/${var.env}/terraform.tfstate"
  lock_key      = "${local.state_key}.tflock"
  state_arn     = "${local.bucket_arn}/${local.state_key}"
  lock_arn      = "${local.bucket_arn}/${local.lock_key}"
  bootstrap_arn = "${local.bucket_arn}/bootstrap/*"

  # The S3 backend lists the state key and, for workspaces, the "env:/" prefix. Neither exposes object data.
  state_list_prefixes = [local.state_key, "env:/*"]

  # OIDC subjects carry the immutable owner and repo IDs.
  oidc_host = "token.actions.githubusercontent.com"
  sub_base  = "repo:${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}"

  # O9: the apply and deploy roles trust the job_workflow_ref claim, pinned to the platform workflow file at each
  # trusted workflow_sha. This local is the single place that holds the value template (outside the release
  # closure, so correcting it after checkpoint step 4a is a patch release). The deploy file does not exist until
  # Phase 2, and platform.lock checks (L3 c) refuse a trusted SHA that contains it, so the deploy role is inert.
  workflow_files = {
    apply  = "reusable-terraform-apply.yml"
    deploy = "reusable-release.yml"
  }
  job_workflow_refs = {
    for role, file in local.workflow_files : role => [
      for sha in var.trusted_workflow_shas : "${var.platform_repository}/.github/workflows/${file}@${sha}"
    ]
  }

  # One entry per role: the allowed subjects, the ref condition and the pinned workflow refs (empty: not pinned).
  trust = {
    # Nonprod plan runs on pull_request (F2, F18) and pins no file (O14). A pull_request_target run has the base
    # ref, so the StringLike (wildcard = PR number only) refuses it even though sub matches. The prod plan role
    # never trusts a pull request: it plans from main or from the prod environment only.
    plan = (
      local.is_prod
      ? {
        subs      = ["${local.sub_base}:ref:refs/heads/main", "${local.sub_base}:environment:${var.env}"]
        ref       = "refs/heads/main"
        ref_test  = "StringEquals"
        workflows = []
      }
      : {
        subs      = ["${local.sub_base}:pull_request"]
        ref       = "refs/pull/*/merge"
        ref_test  = "StringLike"
        workflows = []
      }
    )
    apply = {
      subs      = ["${local.sub_base}:environment:${var.env}"]
      ref       = "refs/heads/main"
      ref_test  = "StringEquals"
      workflows = local.job_workflow_refs.apply
    }
    deploy = {
      subs      = ["${local.sub_base}:environment:${var.env}"]
      ref       = "refs/heads/main"
      ref_test  = "StringEquals"
      workflows = local.job_workflow_refs.deploy
    }
  }

  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn

  role_names = {
    plan   = var.platform.roles.plan
    apply  = var.platform.roles.apply
    deploy = var.platform.roles.deploy
  }
  guardrails_name = "${local.name}-gha-guardrails"

  # Name contract that runtime modules and profiles build against (Phase 2).
  resource_names = {
    ecr_repository = "${local.name}-app"
    boundary       = "${local.name}-workload-boundary"
    secret_prefix  = "${var.platform.prefix}/${var.env}"
  }

  # ARN builders.
  iam_arn        = "arn:${local.partition}:iam::${local.account_id}"
  svc_arn        = { for s in ["ecr", "logs", "secretsmanager"] : s => "arn:${local.partition}:${s}:${local.region}:${local.account_id}" }
  boundary_arn   = "${local.iam_arn}:policy/${local.resource_names.boundary}"
  ecr_repo_app   = "${local.svc_arn["ecr"]}:repository/${local.resource_names.ecr_repository}"
  ecr_repo_env   = "${local.svc_arn["ecr"]}:repository/${local.name}-*"
  secret_pattern = "${local.svc_arn["secretsmanager"]}:secret:${local.resource_names.secret_prefix}/*"
}
