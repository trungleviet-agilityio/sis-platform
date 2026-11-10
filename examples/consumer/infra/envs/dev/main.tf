# Example env root (ADR 0002 W3, W4, M7): the smallest root the reusable plan and apply workflows accept, so the
# canary's callers can run (checkpoint step 8). Contract for every `infra/envs/<env>/`:
#   - an empty `backend "s3" {}`: the workflow composes bucket, key, region and the lock at run time (T3);
#   - a committed `.terraform.lock.hcl` (init runs with -lockfile=readonly; providers from hashicorp only);
#   - `variable "platform"`: the workflow passes the M7 env slice with -var-file (never committed).
# Phase 2 replaces the terraform_data with the runtime module, pinned to release_sha.
terraform {
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
  }

  backend "s3" {}
}

variable "platform" {
  description = "The M7 env slice from `validate.py --emit tfvars --env <env>` (key `platform`)."
  type        = any
}

provider "aws" {
  region = var.platform.region

  default_tags {
    tags = {
      Project   = var.platform.project.name
      Env       = var.platform.env
      Tier      = var.platform.tier
      Owner     = var.platform.project.owner
      ManagedBy = "terraform"
      Platform  = "sis-platform"
    }
  }
}

# One change with no AWS resource, so the first plan and apply prove the pipeline, not a runtime.
resource "terraform_data" "canary" {
  input = "${var.platform.prefix}-${var.platform.env}"
}

output "canary" {
  description = "The env name the pipeline applied."
  value       = terraform_data.canary.output
}
