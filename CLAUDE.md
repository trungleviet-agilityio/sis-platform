# sis-platform

Shared delivery platform for the sis-dev projects: the parts every project needs to ship an app to AWS through
GitHub Actions and Terraform (account bootstrap, OIDC roles, supply chain checks, reusable workflows), plus one
runtime adapter per compute target (Lambda, ECS Fargate, EC2, EKS). A project describes itself in a
`platform.yaml` manifest; an intake interview produces that manifest from the user's product idea.

`docs/adr/` holds locked decisions (read `0001-*.md` first). Reference implementations this platform is extracted
from: `ship-it-safely` (ECS Fargate, frozen by its ADR 0010 T8) and `ship-it-serverless` (Lambda Web Function).
The phase plan and progress tracker are the maintainer's working notes, kept outside the repo.

## Rules

- Work one phase at a time: ADR first (`proposed`, then `accepted` by the user), then build, verify, and stop at
  the checkpoint with the exact commands for the user.
- Design at the level of an AWS Certified Solutions Architect Professional (SAP-C02). Every ADR has a
  `## Well-Architected review` table covering the six pillars (operational excellence, security, reliability,
  performance efficiency, cost optimization, sustainability), citing the pillar best practices it meets and the
  gaps it leaves: https://docs.aws.amazon.com/wellarchitected/latest/framework/the-pillars-of-the-framework.html
- Never add `PLAN.md`, `PROGRESS.md` or another copy of the working notes to the repo.
- Never run `terraform apply`, `terraform destroy`, `terraform import`, `terraform state rm|mv|push`,
  `aws secretsmanager put-secret-value|get-secret-value`, `aws iam create-access-key`, `gh pr merge`,
  `gh workflow run` or `gh secret set`. Prepare the command; the user runs it. Guardrail: `.claude/settings.json`.
- This shell has no AWS credentials on purpose. Do not ask for them or export a profile.
- Never commit secrets, account IDs, a real `.env`, `*.tfstate`, `*.tfvars` or plan files. The repo is public.
- Look up current versions and commit SHAs for actions and tools; never guess them. Pin actions by SHA.
- Run checks through `make` (`make help`); `make check` runs everything a PR must pass. No `apply` or `destroy`
  targets, ever.
- Conventional Commits; trunk-based: short feature branch, PR into `main`, squash merge.
- Consumers pin this repo by tag (`vX.Y.Z`). A change to a reusable workflow path or to a module input is a
  breaking change: say so in the PR and bump the major version (from 1.0.0 on).

## Agent team

Same roles as the `sis-team` plugin in `ship-it-safely`: `solution-architect` writes the ADR (read-only),
`devops-engineer` and `backend-dev` build in their own worktrees with TDD, and `e2e`, `reviewer`,
`security-reviewer`, `code-simplifier` verify without editing files.

| Agent | Owns |
|---|---|
| `backend-dev` | `intake/**` (the manifest schema, validator and decision rules, Python) |
| `devops-engineer` | `modules/**`, `adapters/**`, `.github/**`, `.claude-plugin/**`, `templates/**`, repo tooling (`Makefile`, `.pre-commit-config.yaml`, `pyproject.toml`, `mise.toml`, `scripts/**`) |

The orchestrating session owns the repo `README.md`, `CLAUDE.md` and `docs/**`. Build agents never edit them.
