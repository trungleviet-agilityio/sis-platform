output "role_arns" {
  description = "The plan, apply and deploy role ARNs. Not secret; the owner records them as GitHub environment values."
  value = {
    plan   = module.account_bootstrap.plan_role_arn
    apply  = module.account_bootstrap.apply_role_arn
    deploy = module.account_bootstrap.deploy_role_arn
  }
}

output "state_bucket_name" {
  description = "State bucket of this env."
  value       = module.account_bootstrap.state_bucket_name
}
