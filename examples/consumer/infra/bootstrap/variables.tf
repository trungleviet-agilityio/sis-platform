variable "env" {
  type        = string
  description = "Environment name (a key under envs in platform.yaml)."
}

variable "platform" {
  type        = any
  description = "The env slice of the resolved plan: `validate.py platform.yaml --emit tfvars --env <env>`, key `platform`. The module checks its shape."
}

variable "account_id" {
  type        = string
  description = "AWS account ID of this env. Lives only in the gitignored accounts/<env>.tfvars, never in git."
}

variable "github_owner" {
  type        = string
  description = "GitHub user or organization that owns this repository."
}

variable "github_repo" {
  type        = string
  description = "This repository's name."
}

variable "github_owner_id" {
  type        = string
  description = "Immutable numeric ID of the GitHub owner."
}

variable "github_repo_id" {
  type        = string
  description = "Immutable numeric ID of this repository."
}

variable "notification_email" {
  type        = string
  sensitive   = true
  description = "Address subscribed to the notify topic. Lives only in the gitignored accounts/<env>.tfvars."
}
