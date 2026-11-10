# Credit: adapted from ship-it-serverless infra/terraform/bootstrap/ecr.tf (lab ADR 0012 L4, L8).
# T5: one repository per account, <prefix>-<env>-app. It lives in bootstrap, not in an env root, so destroying an
# env never deletes the images its releases run. A KMS CMK is out of Phase 1 (changing encryption later replaces the
# repository; accepted). Promotion is deferred to Phase 2 (T6).

locals {
  # Newest tagged images kept: 20 in nonprod, 50 in prod. In Phase 2 the adapter marks `live` and `prev` so they
  # never expire (F34, C); until then no image is live.
  ecr_keep_tagged   = local.is_prod ? 50 : 20
  ecr_untagged_days = 14
}

resource "aws_ecr_repository" "app" {
  name                 = local.resource_names.ecr_repository
  image_tag_mutability = "IMMUTABLE"
  # Kept false on purpose: a bootstrap destroy must not delete release images. Empty the repository by hand first.
  force_delete = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${local.ecr_untagged_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = local.ecr_untagged_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the newest ${local.ecr_keep_tagged} tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = local.ecr_keep_tagged
        }
        action = { type = "expire" }
      },
    ]
  })
}

# The runtime profile supplies the repository policy (for example the Lambda pull statement with exact sourceArn
# values). Only the admin who applies bootstrap may change it: no CI role holds ecr:SetRepositoryPolicy.
resource "aws_ecr_repository_policy" "app" {
  count = var.ecr_repository_policy_json == null ? 0 : 1

  repository = aws_ecr_repository.app.name
  policy     = var.ecr_repository_policy_json
}
