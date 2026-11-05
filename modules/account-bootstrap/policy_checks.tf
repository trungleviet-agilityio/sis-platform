# T8: cheap structural checks on the composed policies, after normalizing Statement and Action to lists (IAM
# accepts a single object or a single string). The full lint lives in one place, scripts/tf/policy.py (T11).
# Checked here: no Allow with a `*` or `iam:*` action, no NotAction, no NotResource (any effect, in string and list
# form). The preconditions that use the result sit on the composed role policies in iam_apply.tf and iam_deploy.tf.

locals {
  composed_policies = {
    apply  = var.apply_policy_json
    deploy = var.deploy_policy_json
  }

  # null when the document is not valid JSON or has no Statement.
  policy_statement_raw = {
    for k, j in local.composed_policies : k => j == null ? null : try(jsondecode(j).Statement, null)
  }

  # flatten([x]) turns a single statement object into a one element list and keeps a list as it is.
  policy_statements = {
    for k, s in local.policy_statement_raw : k => flatten([for r in [s] : r if r != null])
  }

  policy_violations = {
    for k, stmts in local.policy_statements : k => concat(
      local.composed_policies[k] != null && local.policy_statement_raw[k] == null ? ["document is not valid JSON or has no Statement"] : [],
      flatten([
        for i, s in stmts : concat(
          (
            try(s.Effect, "") == "Allow"
            && anytrue([for a in flatten([try(s.Action, [])]) : contains(["*", "*:*", "iam:*"], lower(a))])
            ? ["statement ${i} allows a * or iam:* action"] : []
          ),
          contains(keys(s), "NotAction") ? ["statement ${i} uses NotAction"] : [],
          contains(keys(s), "NotResource") ? ["statement ${i} uses NotResource"] : [],
        )
      ]),
    )
  }
}
