# Credit: adapted from ship-it-safely and ship-it-serverless infra/terraform/bootstrap/variables.tf.

variable "env" {
  type        = string
  description = "Environment name (the key under envs in platform.yaml)."

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.env))
    error_message = "env must be 2 to 8 lowercase letters and digits, starting with a letter."
  }
}

variable "platform" {
  type = object({
    env                 = optional(string)
    tier                = string
    prefix              = string
    region              = string
    deploy_role_profile = string
    budget_monthly_usd  = number
    roles = object({
      plan   = string
      apply  = string
      deploy = string
    })
    observability = object({
      notify = string
    })
  })
  description = "The env slice of the resolved plan (ADR 0002, M6 and M7): the validator's `--emit tfvars --env <e>` output, key `platform`. The slice is flat and carries more keys than the module reads (project, runtime, probes, built and so on); the type keeps only what it needs, and `env`, when present, must equal the `env` input. `prefix` is the project prefix; resources are named <prefix>-<env>. `roles` are names, never ARNs, and must equal <prefix>-<env>-gha-{plan,apply,deploy}. `observability.notify` is the SNS topic this module creates (M10)."

  validation {
    condition     = var.platform.env == null || var.platform.env == var.env
    error_message = "platform.env, when present, must equal env."
  }

  validation {
    condition     = contains(["prod", "nonprod"], var.platform.tier)
    error_message = "platform.tier must be prod or nonprod."
  }

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,9}$", var.platform.prefix))
    error_message = "platform.prefix must be 2 to 10 lowercase letters or digits, starting with a letter."
  }

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]$", var.platform.region))
    error_message = "platform.region must look like ap-southeast-1."
  }

  validation {
    condition     = var.platform.budget_monthly_usd > 0
    error_message = "platform.budget_monthly_usd must be positive."
  }

  validation {
    condition = (
      var.platform.roles.plan == "${var.platform.prefix}-${var.env}-gha-plan"
      && var.platform.roles.apply == "${var.platform.prefix}-${var.env}-gha-apply"
      && var.platform.roles.deploy == "${var.platform.prefix}-${var.env}-gha-deploy"
    )
    error_message = "platform.roles must be <prefix>-<env>-gha-plan, -apply and -deploy."
  }

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,200}$", var.platform.observability.notify))
    error_message = "platform.observability.notify must be a valid SNS topic name."
  }
}

variable "github_owner" {
  type        = string
  description = "GitHub user or organization that owns the consumer repository."

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+$", var.github_owner))
    error_message = "github_owner may contain letters, digits and hyphens only."
  }
}

variable "github_repo" {
  type        = string
  description = "Consumer repository name."

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.github_repo))
    error_message = "github_repo may contain letters, digits, dots, underscores and hyphens only."
  }
}

variable "github_owner_id" {
  type        = string
  description = "Immutable numeric ID of the GitHub owner."

  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "github_owner_id must contain digits only."
  }
}

variable "github_repo_id" {
  type        = string
  description = "Immutable numeric ID of the consumer repository."

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repo_id))
    error_message = "github_repo_id must contain digits only."
  }
}

variable "platform_repository" {
  type        = string
  description = "owner/repo of the platform that hosts the reusable workflows the apply and deploy roles trust."
  default     = "trungleviet-agilityio/sis-platform"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.platform_repository))
    error_message = "platform_repository must look like owner/repo."
  }
}

variable "trusted_workflow_shas" {
  type        = list(string)
  description = "The workflow_sha values the apply and deploy roles trust, N and N-1 (platform.lock trusted_workflow_shas; ADR 0002, L1, O9, O10). One or two distinct 40-hex commit SHAs."

  validation {
    condition     = length(var.trusted_workflow_shas) >= 1 && length(var.trusted_workflow_shas) <= 2
    error_message = "trusted_workflow_shas must hold 1 or 2 values (N and N-1)."
  }

  validation {
    condition     = alltrue([for s in var.trusted_workflow_shas : can(regex("^[0-9a-f]{40}$", s))])
    error_message = "every trusted_workflow_shas value must be a 40-character lowercase hex commit SHA."
  }

  validation {
    condition     = length(distinct(var.trusted_workflow_shas)) == length(var.trusted_workflow_shas)
    error_message = "trusted_workflow_shas values must be distinct."
  }
}

variable "notification_email" {
  type        = string
  description = "Address subscribed to the notify topic (budget, anomaly and OIDC alerts). Confirm the subscription once."
  sensitive   = true

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.notification_email))
    error_message = "notification_email must be a valid email address."
  }
}

variable "create_oidc_provider" {
  type        = bool
  description = "Create the GitHub OIDC provider. Set false when the account already has one: an account holds a single GitHub provider, which is then looked up (ADR 0002, T2, F25)."
  default     = true
}

variable "create_trail" {
  type        = bool
  description = "Create the multi-region CloudTrail trail and its bucket. Set false when the account already has a trail, so management events are not paid for twice."
  default     = true
}

variable "create_access_analyzer" {
  type        = bool
  description = "Create an IAM Access Analyzer external access analyzer for the account."
  default     = true
}

variable "enable_guardduty" {
  type        = bool
  description = "Enable a GuardDuty detector. Off by default: free for 30 days, then billed by volume (ADR 0002, T7). The owner turns it on per account."
  default     = false
}

variable "create_anomaly_monitor" {
  type        = bool
  description = "Create a Cost Anomaly Detection monitor and subscription (free)."
  default     = true
}

variable "apply_policy_json" {
  type        = string
  description = "Composed permissions of the apply role, from the consumer root's apply-profile module (ADR 0002, T8). Null: the role has state access only. Checked structurally; the full lint is scripts/tf/policy.py."
  default     = null
}

variable "deploy_policy_json" {
  type        = string
  description = "Composed permissions of the deploy role, from the consumer root's deploy-profile module (T8). Null: the role has image push to the env repository only."
  default     = null
}

variable "ecr_repository_policy_json" {
  type        = string
  description = "Repository policy of the env ECR repository, from the runtime profile (for example the Lambda pull statement). Null: no repository policy. Promotion is deferred to Phase 2 (T6)."
  default     = null
}

variable "deploy_profile_name" {
  type        = string
  description = "Name of the deploy profile module the root wired into deploy_policy_json. It must equal platform.deploy_role_profile whenever deploy_policy_json is set (T8)."
  default     = null
}
