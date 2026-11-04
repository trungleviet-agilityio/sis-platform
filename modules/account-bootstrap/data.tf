# Credit: adapted from ship-it-safely infra/terraform/bootstrap/data.tf.
data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

# T2: an account holds one GitHub OIDC provider (F25), so a shared account looks it up instead of creating it.
data "aws_iam_openid_connect_provider" "github" {
  count = var.create_oidc_provider ? 0 : 1

  url = "https://${local.oidc_host}"
}
