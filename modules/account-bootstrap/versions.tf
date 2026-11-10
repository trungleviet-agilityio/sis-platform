# Credit: adapted from ship-it-safely infra/terraform/bootstrap/versions.tf (lab ADR 0002, B1, B2).
# No provider or backend block lives in this module (ADR 0002, T1): the consumer root infra/bootstrap owns them,
# together with allowed_account_ids and default_tags.
terraform {
  # use_lockfile (consumer backend) is GA from 1.11; mocked tests need 1.7 or later.
  required_version = ">= 1.11, < 2.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71" # bucket_namespace needs 6.37 or later
    }
  }
}
