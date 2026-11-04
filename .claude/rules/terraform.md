---
paths:
  - "modules/**"
  - "scripts/tf/**"
---

# Terraform rules

- Modules have no `provider` or `backend` block. The consumer root owns them, with `allowed_account_ids` and
  `default_tags`.
- Tests first: `*.tftest.hcl` with `mock_provider "aws"` and `override_during = plan` where needed. The only fake
  account ID is `123456789012`. A mock cannot see missing read actions, so the first apply of a new role ends with
  the A7 CloudTrail AccessDenied check (owner).
- Every module has a `README.md` ending in `<!-- BEGIN_TF_DOCS -->` / `<!-- END_TF_DOCS -->`, regenerated with
  `terraform-docs --config modules/.terraform-docs.yml modules/<m>`. `make tf-check` fails when it is stale.
- Module sources are local paths or sis-platform pinned by commit SHA, never a tag or a branch
  (`scripts/tf/resolved-sources.sh`).
- Allow statements use no `*` or `iam:*` action, no `NotAction` or `NotResource`, and no wildcard `Resource` outside
  the allowlist in `scripts/tf/policy.py`. `policy.py` is the one full policy linter (ADR 0002 T8).
- Workload roles carry the permissions boundary. `iam:PassRole` needs `iam:PassedToService`. A CI role never writes
  the boundary, the gha roles or the state bucket policy (guardrails).
- Versions are looked up live and pinned in `mise.toml`. Never add `apply`, `destroy` or `import` targets, and never
  run them: the owner does.
