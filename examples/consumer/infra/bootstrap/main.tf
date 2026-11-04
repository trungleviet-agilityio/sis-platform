# Example consumer bootstrap root (ADR 0002, T1). The owner applies it by hand, once per account and env.
# It owns the provider and the backend; the module has neither.
#
# Run (from the consumer repo root; account inputs never enter git, T3):
#   python3 .platform/intake/sis_intake/validate.py platform.yaml --emit tfvars --env dev > "$TMPDIR/platform-dev.tfvars.json"
#   terraform -chdir=infra/bootstrap init -backend=false
#   terraform -chdir=infra/bootstrap plan -var-file=accounts/dev.tfvars -var-file="$TMPDIR/platform-dev.tfvars.json"

terraform {
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
  }

  # Partial backend: bucket, key and region come from the gitignored accounts/<env>.backend.hcl (T3).
  backend "s3" {
    use_lockfile = true
  }
}

provider "aws" {
  region              = var.platform.region
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      Project         = var.platform.project.name
      Env             = var.env
      Tier            = var.platform.tier
      Owner           = var.platform.project.owner
      ManagedBy       = "terraform"
      Platform        = "sis-platform"
      PlatformVersion = local.lock.version
    }
  }
}

locals {
  # platform.lock is JSON on purpose: Terraform reads it here, and the P9 check reads it in CI (L1).
  lock = jsondecode(file("${path.root}/../../platform.lock"))
}

module "account_bootstrap" {
  # In a real consumer this is the sis-platform release, pinned by commit (L3, H9):
  #   source = "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/account-bootstrap?ref=<release_sha>"
  # This example lives inside the sis-platform checkout, so it uses the local path instead.
  source = "../../../../modules/account-bootstrap"

  env                   = var.env
  platform              = var.platform
  github_owner          = var.github_owner
  github_repo           = var.github_repo
  github_owner_id       = var.github_owner_id
  github_repo_id        = var.github_repo_id
  trusted_workflow_shas = local.lock.trusted_workflow_shas
  notification_email    = var.notification_email
}
