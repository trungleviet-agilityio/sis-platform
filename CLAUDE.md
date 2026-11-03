# sis-platform

Shared delivery platform for the sis-dev projects: account bootstrap, OIDC roles, supply chain checks, reusable
workflows, and one runtime adapter per compute target (Lambda, ECS Fargate, EC2, EKS). A project describes itself
in `platform.yaml`; the intake interview turns a product idea into that manifest. Decisions: `docs/adr/` (read
`0001-*.md` first). Reference labs: `ship-it-safely` (ECS, frozen) and `ship-it-serverless` (Lambda). Working
notes stay outside the repo.

Hard limits are backed by the deny rules in `.claude/settings.json` and, server side, by the `main` branch
ruleset; the sis-team guard joins them in Phase 1. The deny rules are globs with known gaps (other spellings of
`git push` to `main`, `gh api` writes, reading secret files through `cat`), accepted until that guard lands. Path
rules in `.claude/rules/` load with the files they cover.

## Rules

- One phase at a time: ADR (`proposed`, then `accepted` by the owner), build, verify, then stop at the checkpoint
  with the exact commands for the owner.
- Autopilot offline (owner, 2026-11-03), when the owner asks for it: several phases are drafted, cross-reviewed,
  built and verified on a stack of local branches (`phase-<n>-<slug>`, each cut from the previous one) before the
  owner accepts them. ADRs stay `proposed`. Each ADR gets its own docs PR (`docs/adr-NNNN-<slug>`, base `main`)
  and each phase build gets a PR stacked on its ADR PR. Nothing is merged or applied, and nothing touches AWS. Every
  ADR gets a challenger review and every build sub-ticket an independent peer review before the verify agents.
  The owner accepts the whole stack at the end.
- Push feature branches and open PRs. Never merge, run or rerun a workflow, approve a deployment, write through
  `gh api`, or push to `main`. Never apply, destroy, import or move Terraform state, or touch secret values:
  prepare the command, the owner runs it.
- This shell has no AWS credentials on purpose. Do not ask for them or export a profile.
- The repo is public: never commit secrets, account IDs, a real `.env`, `*.tfstate`, `*.tfvars` or plan files.
  Never add `PLAN.md` or `PROGRESS.md`.
- Look up versions and commit SHAs live; never guess them. Pin actions by SHA.
- `make check` runs everything a PR must pass (`make help`). No `apply` or `destroy` targets, ever.
- Conventional Commits; short feature branch, PR into `main`, squash merge. Consumers pin a tag `vX.Y.Z`; a
  reusable workflow path, module input, adapter contract or `schema_version` change is a major bump.
- Design at AWS Solutions Architect Professional (SAP-C02) level. Every ADR has a `## Well-Architected review`
  table over the six pillars:
  https://docs.aws.amazon.com/wellarchitected/latest/framework/the-pillars-of-the-framework.html
- ADR facts are marked (V) seen in official docs, (S) secondary, (C) confirm at a checkpoint. Each decision has
  an options table. Accepted risks are written as "accepted", never "cannot happen".

## Working model: the main session orchestrates, subagents do the work

| Main session | Subagents |
|---|---|
| Talks to the owner, decides, writes ADRs from the architect's draft | Research and doc lookups (`solution-architect`, Explore) |
| Splits the phase into sub-tickets and briefs each one | Build in their own worktree (`backend-dev`, `devops-engineer`) |
| Merges, owns `README.md`, `CLAUDE.md`, `docs/**`, `.claude/**` | Verify (`e2e`, `reviewer`, `security-reviewer`, `code-simplifier`) |
| Re-runs `make check` on the merged branch, writes the checkpoint report | CI triage, log reading, version and SHA lookups |

- A brief stands alone: goal, owned paths, the ADR IDs that are the spec, out of scope, done checks, report format.
- A report is about 60 lines at most: result in one line; files changed; every check run with its result (never
  one it did not run); choices made where the spec was silent; open items. No transcripts or file dumps.
- Independent sub-tickets run in parallel; fix rounds go back to the same subagent. The main session checks the
  report (diff stat, merged `make check`), it does not redo the work. One-off reads stay in the main session.
- A build agent's last commit is never a WIP checkpoint. Shell scripts stay bash 3.2 compatible.

## Agent team

| Agent | Owns |
|---|---|
| `backend-dev` | `intake/**` (manifest schema, validator, rules, intake plugin; Python) |
| `devops-engineer` | `modules/**`, `adapters/**`, `.github/**`, `.claude-plugin/**`, `templates/**`, `Makefile`, `.pre-commit-config.yaml`, `pyproject.toml`, `mise.toml`, `scripts/**` |

Verify agents never edit files; `reviewer` also checks docs drift.
