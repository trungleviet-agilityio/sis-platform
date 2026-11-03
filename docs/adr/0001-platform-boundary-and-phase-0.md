# ADR 0001: Platform boundary for all phases, and Phase 0 scope

- Status: accepted (owner, 2026-11-03)
- Date: 2026-11-03
- Deciders: owner (accepts), solution-architect (drafts)
- Reference implementations: `ship-it-safely` (ECS Fargate, frozen by its ADR 0010 T8), `ship-it-serverless`
  (Lambda Web Function, its ADR 0012)

## Context

The two labs are forks of each other. About 70% is the same code: account bootstrap (OIDC provider, state bucket,
plan/apply/deploy roles, guardrails, budget, monitoring), `scripts/ci|image|guard|aws`, `repo-guard`,
`reusable-terraform-plan`, `oidc-smoke-test`, promote by digest, and the `sis-team` plugin. What differs by runtime
is `modules/app-ecs`, `iam_ecs_boundary.tf`, `scripts/ecs`, the deploy step and `ALB_INGRESS_CIDRS`. Forking
causes drift: the `gh api` guard gap (serverless ADR 0013) had to be fixed twice.

`sis-platform` becomes the single core. It is public, versioned by tag and consumed by thin project repos. The
next real consumer is English for Devs. This ADR fixes the boundary for every phase. It also fixes the exact
scope of Phase 0, which has no AWS code, no Terraform and no credentials.

Inherited rules: no account IDs or secrets in git (public repo); actions pinned by SHA; Claude never applies,
merges, dispatches workflows or approves deployments (repo `CLAUDE.md`, serverless ADR 0013 G1 to G7); app
contract from ship-it-safely ADR 0011 (one port, a health path, `/version` with the commit SHA and image digest);
rollback means redeploying an earlier digest (ship-it-safely ADR 0010 T1).

### Facts checked

(V) = official text seen. (S) = secondary source, or official text seen only through search results. (C) =
confirm at a checkpoint.

| # | Fact | Mark |
|---|---|---|
| F1 | AWS STS supports `token.actions.githubusercontent.com:job_workflow_ref` as a condition key ("the reference path to the reusable workflow for jobs using a reusable workflow"), with string operators. `job_workflow_sha` is **not** an AWS key | V |
| F2 | When a reusable workflow is called, `sub`, `repository` and `ref` describe the **caller**. `job_workflow_ref` describes the **called** workflow as `OWNER/REPO/.github/workflows/FILE@REF` | V |
| F3 | The exact `job_workflow_ref` value when the caller pins `uses:` by commit SHA (expected `...@<40-hex>`) | C, read a real token in Phase 1 |
| F4 | A reusable workflow in a public repository can be called from public and private repos when the caller's Actions policy allows public reusable workflows. The `uses:` ref can be a SHA, tag or branch; GitHub calls the SHA "the safest option". Limits: 10 nesting levels, 50 unique reusable workflows per caller file | V |
| F5 | For a reusable workflow outside the caller's org, the caller must grant `id-token: write` explicitly. `secrets: inherit` works only inside the same org or enterprise | V |
| F6 | User-level Projects can hold issues and PRs from any repository; 50,000 items; 50 fields. Built-in workflows set Done on close and on merge. Auto-add workflows are limited by plan (Free 1, Pro 5) and each one targets one repo | V |
| F7 | Claude Code marketplaces support `git-subdir` plugin sources, which can be pinned to a `ref` or `sha` | V |
| F8 | ECS has native blue/green (2025) and native linear and canary (Oct 2025). These use weighted ALB target groups (or NLB, Service Connect, VPC Lattice), bake times, lifecycle hooks, and alarm-based automatic rollback | S |
| F9 | A Lambda alias can split traffic between two published versions (`AdditionalVersionWeights`). A Function URL can target an alias through a qualifier | S |
| F10 | Whether a Function URL on a weighted alias honors the weights | C |
| F11 | ASG instance refresh supports `CheckpointPercentages` (the last value must be 100), `CheckpointDelay`, up to 10 CloudWatch alarms, and auto rollback. Rollback is unavailable with `$Latest`/`$Default` launch template versions | S |
| F12 | Argo Rollouts: canary uses `setWeight` and `pause` steps; blueGreen uses `activeService`/`previewService` with `autoPromotionEnabled` | S |
| F13 | ECR cross-account replication needs a registry policy only in the destination account (`ecr:ReplicateImage`). It replicates every matching push with no gate | S |
| F14 | Lambda limits: 15 min timeout, 6 MB synchronous payload. HTTP API integration timeout is about 30 s | S |
| F15 | EKS control plane is billed per cluster hour (about 73 USD/month at 0.10 USD/h) | S, C |
| F16 | Whether `actions/setup-python` still serves 3.9 (3.9 is end of life) | C at build |

## Decision

### P. Platform boundary (all phases)

| # | Decision |
|---|---|
| P1 | `sis-platform` owns: `modules/account-bootstrap`, `modules/runtime-<kind>` (`lambda-web`, `lambda-events`, `ecs-fargate`, `ec2-asg`, `eks-workload`), `.github/workflows/*` (reusable, trigger `workflow_call` only, plus the repo's own CI), `adapters/<runtime>/`, `templates/project/` (copier), `intake/` (schema, validator, rules, intake plugin), `plugins/sis-team/` (from Phase 1), and the shared `scripts/` that the reusable workflows run |
| P2 | A project repo owns: `app/`, `infra/bootstrap/` (a root that calls `account-bootstrap`; account tfvars are gitignored), `infra/envs/<env>/` (a root that calls one `runtime-*` module), thin caller workflows, `platform.yaml`, `project.env`, and its own `docs/adr/` |
| P3 | Never in `sis-platform`: account IDs, filled tfvars, state, plan files, secrets, real project names (except in examples). A manifest names accounts by label only (`account: dev`). The label maps to an ID in the project repo's GitHub environment variables |
| P4 | Adapter contract, the same for every runtime: `deploy(env, digest)`, `verify(env)`, `rollback(env, prev_digest)`, `status(env)`. Each is an executable `adapters/<runtime>/<verb>`. Inputs come from env vars; output is one JSON line (`env`, `digest`, `sha`, `version`, `traffic`, `state`). Exit codes: 0 ok, 1 failed, 2 refused. Every verb is idempotent. Rollback is always "deploy an earlier digest", whatever the strategy |
| P5 | Terraform owns the runtime shape; the deploy swaps only the image digest and traffic (lab ADR 0005 F2) |
| P6 | YAGNI build order. `lambda-web` is first (consumer: ship-it-serverless). `ecs-fargate` is built when a real consumer selects it (ship-it-safely is a frozen reference, not a consumer). `lambda-events`, `ec2-asg` and `eks-workload` come later. The schema accepts every runtime; the validator warns "adapter not built yet" (V17) |
| P7 | The EKS cluster is a shared asset: `modules/eks-cluster` is applied once in a shared workloads account. `eks-workload` creates only the namespace, Pod Identity role and Argo CD Application of one project |
| P8 | One version line: semver tags `vX.Y.Z` version modules, workflows, adapters, schema and plugins together. The repo stays 0.x until a consumer deploys through it, then 1.0.0. These are breaking changes (major bump): a reusable workflow path, a module input, the adapter contract, `schema_version` |
| P9 | A consumer pins one version, recorded in `platform.yaml` (`platform.version`), in three places: workflow `uses:` by SHA with a `# vX.Y.Z` comment, module `source = "git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/<m>?ref=<sha>"`, and the marketplace plugin `ref`/`sha`. A reusable check (Phase 1) fails when the three differ |
| P10 | Multi-account (SEC01-BP01, COST02-BP03): one account per project environment (`<prefix>-dev`, `<prefix>-prod`) in AWS Organizations. OUs: `Security` (log archive and audit, later), `Workloads/NonProd`, `Workloads/Prod`, `Shared` (EKS cluster, central artifacts if needed), `Sandbox`. No Control Tower for now (AWS Config cost at a 20 USD budget). Gap closed by an `org-baseline` phase |
| P11 | SCPs (later phase, `modules/org-baseline`, applied by the owner): deny regions outside the allowlist (global services exempt), deny `organizations:LeaveOrganization`, deny root user actions, deny stopping CloudTrail and GuardDuty, deny `iam:CreateAccessKey` and `iam:CreateUser` in workload OUs. GuardDuty and Security Hub get a delegated admin in the audit account |
| P12 | Identities. Humans: IAM Identity Center permission sets (SEC02-BP04). CI: per-account OIDC roles (plan/apply/deploy) as in the labs (SEC02-BP02). No cross-account CI hub role: a hub role widens the blast radius of one trust mistake |
| P13 | Promotion stays copy-by-digest from the dev ECR to the prod ECR, gated by a GitHub environment. The prod deploy role pulls from the dev repo through a repository policy. Rejected: ECR cross-account replication (F13), because it pushes every dev image to prod with no gate. It is allowed later for cross-region DR copies. A central artifact account is deferred until there are more than two envs or projects. Encryption is AES256 by default; a KMS CMK (key policy grant to the prod deploy role) only when the intake answer `compliance.kms_cmk` is true |
| P14 | Phases: 0 contract (this ADR). 1 extract shared core (`account-bootstrap`, scripts, repo-guard, reusable plan and apply workflows, OIDC change O*, sis-team move B*). 2 `runtime-lambda-web` and its adapter; ship-it-serverless consumes them. 3 English for Devs intake and bootstrap. Later: `ecs-fargate`, `org-baseline`, `ec2-asg`, EKS |

### M. Manifest and release axes

| # | Decision |
|---|---|
| M1 | `platform.yaml`, `schema_version: 1`. Top level: `project`, `platform`, `workload`, `runtime`, `ci`, `budget`, `dr`, `compliance`, `database`, `envs`. `additionalProperties: false` everywhere |
| M2 | Three independent release axes per env: `delivery` (`push`, `gitops`); `release.strategy` (`all-at-once`, `rolling`, `canary`, `linear`, `blue-green`) with `steps` (percent, rising, last 100), `bake_minutes`, `rollback` (`alarm`, `health`, `manual`); `release.engine` (`auto`, `pipeline`, `codedeploy`, `ecs-native`, `argo-rollouts`, `asg`) |
| M3 | `engine: auto` resolves to: lambda to `pipeline`, ecs to `ecs-native`, ec2 to `asg`, eks to `argo-rollouts`. The validator prints the resolved engine and a `deploy_role_profile` (for example `lambda-alias`, `ecs-native`, `codedeploy-ecs`). Bootstrap reads the profile (Phase 1), because the engine changes the deploy role permissions |
| M4 | Compatibility matrix (data in `intake/rules/compat.json`, see below) |
| M5 | Defaults per runtime (data, used by intake and printed by the validator), see table D |

Example (valid, trimmed):

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/trungleviet-agilityio/sis-platform/v0.1.0/intake/schema/platform.schema.json
schema_version: 1
project: {name: ship-it-serverless, prefix: sis}
platform: {version: v0.1.0}
workload: {shape: web, port: 8080, health_path: /health, max_duration_seconds: 10, max_payload_mb: 1}
runtime: {kind: lambda-web, arch: x86_64, front_door: http-api}
ci: {provider: github-actions}
budget: {monthly_usd: 20}
dr: {strategy: backup-restore, rto_minutes: 240, rpo_minutes: 1440}
database: {kind: none}
envs:
  dev:  {account: dev, region: ap-southeast-1, delivery: push, scale_to_zero: true,
         release: {strategy: canary, steps: [10, 100], bake_minutes: 5, rollback: alarm, engine: pipeline}}
  prod: {account: prod, region: ap-southeast-1, delivery: push, promote_from: dev,
         release: {strategy: all-at-once, rollback: manual, engine: auto}}
```

Compatibility matrix (E = error, W = warning):

| Runtime | Strategies | Engines | gitops | Notes |
|---|---|---|---|---|
| lambda-web, lambda-events | all-at-once, canary, linear | pipeline, codedeploy | E (V03) | Alias weights (F9). `rolling` and `blue-green` E with the hint "alias flip = all-at-once" |
| ecs-fargate | all-at-once, rolling, canary, linear, blue-green | ecs-native, codedeploy, pipeline (rolling only) | E | Canary, linear and blue-green need `front_door: alb` (F8) |
| ec2-asg | rolling, canary, blue-green | asg, codedeploy | E | Rolling = instance refresh with checkpoints (F11); canary and blue-green = weighted target groups, need an ALB |
| eks-workload | rolling, canary, blue-green | argo-rollouts | allowed, recommended | Argo CD/Flux delivers, Argo Rollouts releases (F12) |

Validator rule catalog (`intake/rules/rules.json`; every rule carries pillars and Well-Architected references):

| ID | Rule | Sev | Pillars | WA ref |
|---|---|---|---|---|
| V01 | `canary` or `linear` requires `rollback: alarm` | E | REL, OPS | OPS06-BP04, REL08-BP05 |
| V02 | `canary`/`linear` need `steps` rising and ending at 100, and `bake_minutes` >= 1 | E | REL | OPS06-BP03 |
| V03 | `delivery: gitops` only for `eks-workload` | E | OPS | OPS06-BP03 |
| V04 | (runtime, strategy, engine) must be in the matrix | E | OPS, REL | REL08-BP05 |
| V05 | canary, linear or blue-green on ecs-fargate or ec2-asg need `front_door: alb` | E | REL | OPS06-BP03 |
| V06 | ALB needed and `budget.monthly_usd` < 40 | W | COST | COST02-BP05 |
| V07 | `blue-green` doubles capacity during a deploy | W | COST, SUS | SUS02-BP01 |
| V08 | Lambda runtime with `max_duration_seconds` > 900, `max_payload_mb` > 6, or `needs` containing gpu, os or licence | E | PERF | PERF01, PERF02-BP01 |
| V09 | `front_door: http-api` with `max_duration_seconds` > 29 | E | PERF, REL | PERF02-BP02 |
| V10 | A 12-digit number anywhere in the manifest, including placeholders | E | SEC | SEC01-BP06 |
| V11 | A `prod` env needs `promote_from` (one artifact promoted by digest) | E | SEC, REL | SEC11-BP06, REL08-BP04 |
| V12 | `database.kind != none` and a strategy that runs two versions at once (all except all-at-once) needs `database.schema_change: expand-contract` | E | REL | REL08-BP02 |
| V13 | `dr.rto_minutes` < 60 with `backup-restore`, or < 10 without warm-standby or multi-site | W | REL | REL13-BP01, REL13-BP02 |
| V14 | `warm-standby` or `multi-site` with `budget.monthly_usd` < 100 | W | COST, REL | COST02-BP05 |
| V15 | `eks-workload` with `budget.monthly_usd` < 100 (control plane, F15) | W | COST | COST05 |
| V16 | `scale_to_zero` or `fargate_spot` on prod | W | REL | REL10 |
| V17 | Runtime adapter or `ci.provider: codepipeline` not built yet | W | OPS | OPS07 |
| V18 | `prod` with `rollback: manual` and a strategy other than all-at-once | W | OPS | OPS06-BP01 |

### D. Runtime defaults (intake proposes them; the user can override)

| Runtime | Front door default | Network | DR default | Cost default | Sustainability default |
|---|---|---|---|---|---|
| lambda-web | HTTP API (throttle as cost ceiling). Function URL when budget-first; CloudFront + WAF only when the intake says public and abuse-prone | No VPC. If a DB needs a VPC: S3/DynamoDB gateway endpoints (free) plus only the interface endpoints needed; no NAT | backup-restore (IaC + ECR + state); pilot-light = ECR cross-region replication + IaC in a second region | arm64 for new apps; Compute Savings Plan only when steady prod spend is known; power tuning in Phase 2 | Scale to zero by design; arm64 (SUS05-BP02) |
| ecs-fargate | ALB (needed for canary and blue-green) | Private subnets + VPC endpoints when few AZs and low egress; NAT when egress is broad. The intake asks egress needs (COST08) | backup-restore; warm-standby = scaled-down service in a second region | arm64, Fargate Spot in dev only, Savings Plan for steady prod | dev desired count 0 or destroy after the session (lab pattern) |
| ec2-asg | ALB | Private + NAT or SSM endpoints | AMI + launch template in a second region (pilot light) | Graviton, Savings Plans, Spot in dev | Right-size with Compute Optimizer; ASG min 0 in dev |
| eks-workload | ALB via the Load Balancer Controller | Shared cluster VPC | GitOps re-sync to a second cluster | Shared cluster to amortize the control plane; Karpenter with Spot in dev | Bin-packing on the shared cluster; arm64 node pools |

Migration (7 Rs) is one optional intake group, asked only when the app already exists. Rehost maps to ec2-asg,
replatform to ecs-fargate, refactor to lambda-* or ecs. Retire, retain, relocate and repurchase end the intake
with a note.

### O. OIDC trust when deploy moves to a reusable workflow

| # | Decision |
|---|---|
| O1 | Apply and deploy trust keep: `aud`, immutable `sub` with `environment:<env>`, `repository_id`, `repository_owner_id`, `ref = refs/heads/main`, `aws:RequestedRegion`. These describe the **caller** (F2), so they still bind the project repo |
| O2 | `job_workflow_ref` (StringEquals, never StringLike) pins the **sis-platform** file at an exact commit: `trungleviet-agilityio/sis-platform/.github/workflows/<file>@<40-hex sha>`. Callers use `uses: trungleviet-agilityio/sis-platform/.github/workflows/<file>@<sha> # vX.Y.Z` |
| O3 | Why SHA and not a tag: a tag can be moved, and AWS cannot see `job_workflow_sha` (F1). A tag pattern (`@refs/tags/v1.*`) would trust any future tag anyone with push can create. The cost: every platform bump needs one bootstrap re-apply per account, by the owner |
| O4 | Each role trusts at most two values, N and N-1 (variable `platform_workflow_refs`, validated as length 1 to 2 and a 40-hex SHA). Rollout of a bump: (1) the owner adds the new SHA and re-applies bootstrap in dev, then prod; (2) PR bumps `uses:` and `platform.version`; merge; deploy to dev; promote; (3) the next bump drops the oldest SHA in the same re-apply. Rolling back the platform = revert the PR; N-1 is still trusted |
| O5 | Gate before any trust change (Phase 1 checkpoint, like lab ADR 0007 A0): the owner dispatches a smoke workflow that calls the reusable workflow by SHA and prints the claims, which confirms F3. If the value is not `@<sha>`, pin the exact string observed; never widen to a wildcard |
| O6 | Callers set `permissions: {contents: read, id-token: write}` on the calling job (F5), pass no secrets (no `secrets: inherit`), and pass the account label, not the ID. The reusable job reads the role ARN from the caller's environment variable (`vars`, C in Phase 1) and masks the account ID with `redact-account-ids.sh` |
| O7 | Reusable workflows declare `on: workflow_call` only, `permissions: {}` at the top, `environment: ${{ inputs.env }}` on the credentialed job, and harden-runner `egress-policy: block` on credentialed jobs |
| O8 | Plan role trust is unchanged (pull_request `sub`, `refs/pull/*/merge`, no `job_workflow_ref`) |

### B. Management: plugin home and board

| # | Decision |
|---|---|
| B1 | `sis-team` has one home: `sis-platform/plugins/sis-team`, listed in `sis-platform/.claude-plugin/marketplace.json` (marketplace `sis-platform`). The plugin entry uses a `git-subdir` source pinned by `ref` and `sha` to the release tag (F7). Project repos enable it with `extraKnownMarketplaces` and `enabledPlugins` in `.claude/settings.json`. No fork per repo |
| B2 | The intake plugin `sis-intake` lives in `intake/` (plugin root = `intake/`) in the same marketplace, so its skill can run `python3 "${CLAUDE_PLUGIN_ROOT}/sis_intake/validate.py"` in any project session |
| B3 | Sequence, so nothing is rewritten: (1) serverless PR `fix/sis-team-guard-gh-writes` (ADR 0013, G1 to G7) merges; (2) the same guard lands in ship-it-safely as the T8 exception; (3) serverless board and re-review PRs (super-board proposal steps 2 and 3) merge; (4) Phase 1 copies `plugins/sis-team` from serverless `main` at a recorded commit SHA into sis-platform. Allowed diff: `plugin.json` (name, repository, version) and README paths only; the PR shows `git diff --no-index` of the two trees; (5) serverless switches to the marketplace and deletes its copy; (6) ship-it-safely keeps its frozen copy (T8) |
| B4 | One user-level GitHub Project, "sis delivery", spans sis-platform and every project repo. Views group by the built-in Repository field (one saved view per repo plus "Needs you" across all). Status columns: Backlog, Planned, Ready, Building, Verify, Needs you, Done, Blocked. Custom fields: `Phase` (text), `Kind` (phase, checkpoint, platform-bump, bug). Rejected: one board per repo, which loses the cross-project "Needs you" queue that the owner asked for |
| B5 | Auto-add is not relied on (Free plan: 1 workflow, F6). `board.py` adds cards explicitly at plan time. Keep the built-in "closed to Done" and "merged to Done" workflows |
| B6 | `board.py` (Phase 1, in the plugin) reads `SIS_BOARD_OWNER` and `SIS_BOARD_PROJECT` from `project.env` and refuses any other project. Its only allow rule is `Bash(python3 *plugins/sis-team/scripts/board.py *)`. "Needs you" cards carry the exact commands; round-2 reviews check prior findings first |
| B7 | A platform bump is a `platform-bump` card in every consumer repo, created by the orchestrator, with the O4 commands in a "Needs you" comment |
| B8 | Claude never merges, dispatches workflows, approves deployments or applies. In sis-platform this holds through the deny list now and the G1 to G7 guard once the plugin moves (Phase 1). Until then, Claude sessions in sis-platform run with the serverless sis-team plugin enabled at user scope (owner choice, Q2) |

### Z. Phase 0 scope

| # | Decision |
|---|---|
| Z1 | In: repo tooling, `intake/` (schema, YAML subset loader, validator, rules data, examples, tests, intake plugin), root `.claude-plugin/marketplace.json` listing `sis-intake`. Out: modules, adapters, reusable deploy workflows, copier template, board script, the sis-team move, anything with AWS, Terraform or `id-token` |
| Z2 | The schema lives at `intake/schema/platform.schema.json` (JSON Schema 2020-12, `$id: urn:sis-platform:platform:1`), owned by backend-dev. Consumers reference the raw URL at a tag. Ownership stays disjoint: backend-dev `intake/**`; devops-engineer `.github/**`, `.claude-plugin/**`, `Makefile`, `.pre-commit-config.yaml`, `pyproject.toml`, `mise.toml`, `scripts/**`; orchestrator `README.md`, `CLAUDE.md`, `docs/**` |
| Z3 | Python. The runtime floor is 3.9, stdlib only, because the intake skill runs under the user's system `python3` (macOS 3.9, as in G7). Ruff `target-version = "py39"`. Dev and CI use 3.13 from `mise.toml`; CI also tests the floor (F16: 3.9, or the oldest version setup-python serves) |
| Z4 | No JSON Schema library at runtime. `sis_intake/schema.py` interprets a fixed keyword subset: `type`, `enum`, `const`, `required`, `properties`, `additionalProperties`, `items`, `pattern`, `minimum`, `maximum`, `minItems`, `$ref` (local `#/$defs`). A test fails if the schema uses any other keyword. CI cross-checks the schema with the pinned `check-jsonschema` pre-commit hooks (`check-metaschema`, and every valid example against the schema) |
| Z5 | YAML. Stdlib has no YAML parser, so `sis_intake/yamlsubset.py` parses a documented subset: block maps and lists, plain or quoted scalars, int, bool, null, comments, flow lists of scalars and flow maps of scalars. It rejects anchors, aliases, tags, multi-docs and multi-line scalars with line numbers (fail closed). A conformance test compares it with `yaml.safe_load` on every example; PyYAML is test-only, hash-locked in `scripts/ci/requirements.txt`. The test is skipped with a notice when PyYAML is missing locally; it always runs in CI |
| Z6 | CLI: `python3 intake/sis_intake/validate.py FILE [--json]`. Exit codes: 0 valid (warnings printed), 1 errors, 2 parse or usage error. Each finding has `id`, `severity`, `path`, `message`, `pillars`, `wa_refs`. It also prints the resolved engine and `deploy_role_profile` |
| Z7 | Rules are data: `intake/rules/questions.json` (question groups, below), `compat.json` (matrix M4), `rules.json` (V01 to V18), `defaults.json` (table D). Python implements one predicate per rule ID. A test asserts that the catalog and the predicates match one to one and that every rule has at least one pillar |
| Z8 | Intake plugin: `intake/.claude-plugin/plugin.json`, `intake/skills/intake/SKILL.md`, `intake/agents/intake-interviewer.md` (tools: Read, Grep, Glob, Bash for the validator only). The interview asks one question at a time, recommends an answer with its pillar, and stops when the manifest validates. It returns three drafts as text (`platform.yaml`, a first ADR, a pipeline proposal); the orchestrating session in the project repo writes them |
| Z9 | CI `.github/workflows/ci.yml`: `pull_request` and `push` to `main`; top-level `permissions: {}`; job `check` has `contents: read`, harden-runner `egress-policy: audit` (no credentials in Phase 0; `block` from Phase 1 on credentialed jobs), actions by SHA, and runs `make check`. The required status check name is `check` |
| Z10 | Done = `make check` green locally and in CI, the ruleset requires `check`, the owner accepts this ADR and creates tag `v0.1.0` |

Intake question groups (`questions.json`), each tagged with the pillars it serves:

| Group | Asks | Pillars |
|---|---|---|
| Q1 Product and workload shape | web, events, worker or batch; port, health path | PERF01, OPS |
| Q2 Limits | longest request or job, payload size, GPU, OS access, licence | PERF02-BP01 |
| Q3 Traffic | steady, spiky or idle; peak RPS; latency target; public or internal | PERF, COST, SUS02-BP01 |
| Q4 Team | skills (Kubernetes, containers, serverless), on-call capacity | OPS (OPS07) |
| Q5 Release and recovery | risk tolerance, release strategy, RTO and RPO, DR strategy | REL13-BP01, OPS06 |
| Q6 Envs, accounts, compliance | env list, account per env, data class, KMS CMK, region | SEC01-BP01, SEC, SUS (region) |
| Q7 Budget | monthly ceiling, pricing model (Spot in dev, Savings Plans) | COST02-BP05, COST07 |
| Q8 CI | GitHub Actions (default) or CodePipeline | OPS05, SEC11-BP06 |
| Q9 Data | database, schema change style (expand/contract) | REL08-BP02 |
| Q10 Existing app (optional) | 7 Rs | PERF01, COST |

## Well-Architected review

| Pillar | Best practices | How the design meets it | Gap and phase that closes it |
|---|---|---|---|
| Operational excellence | OPS05, OPS06-BP01 to BP04, OPS04 | One pipeline shape and one adapter contract per runtime; strategies with bake and automated rollback; `verify` proves SHA and digest; checkpoints with exact commands; board "Needs you" | Observability standard (OPS04 KPIs, tracing) not defined: Phase 2 per runtime module |
| Security | SEC01-BP01, BP06; SEC02-BP02, BP04; SEC11-BP02, BP06, BP07 | Account per env; OIDC with no long-lived keys; trust pinned to caller IDs plus platform SHA; actions pinned by SHA; public repo holds no IDs (V10, pygrep hook); Claude cannot merge or apply (guard) | SCPs, Identity Center, delegated GuardDuty: `org-baseline` phase. Tag immutability: owner checkpoint |
| Reliability | REL08-BP02, BP04, BP05; REL13-BP01, BP02; REL10 | Immutable digests; promote by digest; rollback by digest for every combination; V01, V12 and V13 enforce alarms, schema compatibility and DR realism | DR beyond backup-restore is not built; DR tests (REL13-BP03) when a consumer needs RTO < 1 h |
| Performance efficiency | PERF01, PERF02-BP01, BP04, BP05 | Intake limits map the workload to a runtime (V08, V09); serverless or managed scaling by default | Lambda power tuning and load test step: Phase 2 |
| Cost optimization | COST02-BP03, BP05; COST05; COST07; COST08 | Budget in the manifest, warnings V06, V14, V15; Spot in dev only; scale to zero in dev; NAT avoided by default | Cost allocation tags and per-project budgets in `account-bootstrap`: Phase 1 |
| Sustainability | SUS02-BP01, BP03; SUS05-BP01 to BP03 | arm64 default for new apps; managed services; scale to zero and destroy-after-session in dev; blue-green capacity warning (V07) | Region carbon choice is out of scope (region is fixed by latency and cost) |

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep forking per project | Drift; every security fix lands N times |
| Copier template only, no shared repo | A template copy drifts as soon as it is generated; there is no version to bump |
| Trust a tag pattern in `job_workflow_ref` | Any new matching tag becomes trusted; tags are mutable (O3) |
| Trust the exact tag | Tags can be moved; still needs a re-apply per bump, so it has the cost of SHA pinning without the guarantee |
| Customize `sub` with `include_claim_keys` | An extra repo-level OIDC setting per consumer; AWS reads `job_workflow_ref` directly (F1) |
| `jsonschema` at runtime | Not stdlib; the skill must run under a bare `python3` |
| Manifest as JSON | The owner wants YAML with comments; the subset loader keeps stdlib |
| One GitHub Project per repo | No cross-project "Needs you" view |
| Separate repo for the sis-team plugin | One more version line and release; same owner and cadence as the platform |
| ECR cross-account replication for promotion | Ungated (F13) |
| Control Tower now | Config and guardrail cost against a 20 USD budget; Organizations + SCPs by hand is enough for two or three projects |

## Consequences

- A platform bump costs one bootstrap re-apply per account (O4). This is accepted for an immutable trust anchor.
- Every consumer change of version is one PR plus a "Needs you" card.
- The validator gives the intake and CI one source of truth. The deploy role profile ties manifest choices to IAM
  in Phase 1.
- The YAML subset is a constraint: the intake writes only what the loader reads, and the error names the line.

### Owner checkpoint (Phase 0, run by hand)

1. Review and accept this ADR (status `accepted`).
2. Repo settings (UI or `gh api`): Actions "Allow all actions and reusable workflows" or "selected"; enable
   "Require actions to be pinned to a full-length commit SHA" if offered (C); secret scanning with push
   protection; private vulnerability reporting.
3. Branch ruleset on `~DEFAULT_BRANCH`: deletion, non_fast_forward, pull_request (squash only), required status
   check `check` from GitHub Actions; no bypass actors.
4. Tag ruleset on `refs/tags/v*`: restrict updates and deletions (immutable tags); creation by the owner only.
   Enable immutable releases if offered (C).
5. `make check` locally, then confirm the `check` job is green on the Phase 0 PR. Merge it yourself.
6. `gh release create v0.1.0 --title v0.1.0 --notes "Phase 0: manifest schema and validator"`.
7. Later, before Phase 1: `gh auth refresh -s project`, then `gh project create --owner @me --title "sis delivery"`
   and add the Status options of B4.

## Open questions

| # | Question |
|---|---|
| Q1 | ALB warning threshold: 40 USD per month? (V06) |
| Q2 | Until Phase 1, enable the serverless sis-team plugin at user scope for sis-platform sessions (B8)? |
| Q3 | Should English for Devs run the intake in Phase 3 or earlier, as a dry run against `v0.1.0`? |
| Q4 | Do you accept arm64 as the default for new apps (labs stay x86_64)? |
| Q5 | GitHub plan: Free (1 auto-add) is assumed in B5; confirm |

## Owner answers (2026-11-03)

The owner accepted the ADR without answering the open questions. The orchestrator took the defaults below; the
owner can change any of them in a later PR.

| # | Default taken | Effect |
|---|---|---|
| Q1 | 40 USD per month | V06 threshold in `rules.json` |
| Q2 | Not decided; nothing enabled | No user-scope plugin change. The repo deny list is the only guard until Phase 1 |
| Q3 | Not decided | No effect on Phase 0 |
| Q4 | arm64 is the default for new apps | `defaults.json`; the two lab examples keep `x86_64` |
| Q5 | Free plan assumed | B5 stands (no auto-add) |

## Sources

- AWS IAM, GitHub OIDC condition keys: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_iam-condition-keys.html (V)
- GitHub OIDC reference: https://docs.github.com/en/actions/reference/security/oidc (V)
- GitHub OIDC with reusable workflows: https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows (V)
- Reusable workflows reference (access, limits): https://docs.github.com/en/actions/reference/workflows-and-actions/reusable-workflows (V)
- Reuse workflows (ref and SHA pinning): https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows (V)
- Projects: https://docs.github.com/en/issues/planning-and-tracking-with-projects/managing-items-in-your-project/adding-items-to-your-project, https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically, https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations (V)
- Claude Code marketplaces: https://code.claude.com/docs/en/plugin-marketplaces (V)
- ECS linear and canary: https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-ecs-built-in-linear-canary-deployments, https://aws.amazon.com/blogs/containers/gradual-deployments-in-amazon-ecs-with-linear-and-canary-strategies (S)
- Lambda alias routing: https://docs.aws.amazon.com/lambda/latest/dg/configuring-alias-routing.html (S); Function URL qualifier: https://docs.aws.amazon.com/lambda/latest/api/API_GetFunctionUrlConfig.html (S); limits: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html (S)
- ASG instance refresh: https://docs.aws.amazon.com/autoscaling/ec2/APIReference/API_RefreshPreferences.html (S)
- Argo Rollouts: https://argo-rollouts.readthedocs.io/en/stable/features/canary/ and https://argo-rollouts.readthedocs.io/en/stable/features/bluegreen/ (S)
- ECR replication: https://docs.aws.amazon.com/AmazonECR/latest/userguide/replication.html, https://docs.aws.amazon.com/AmazonECR/latest/userguide/registry-permissions-create-replication.html (S)
- EKS pricing: https://aws.amazon.com/eks/pricing/ (S)
- Well-Architected pillars: https://docs.aws.amazon.com/wellarchitected/latest/framework/the-pillars-of-the-framework.html; questions opened: ops-04, ops-06, sec-01, sec-02, sec-11, rel-08, rel-13, perf-02, cost-02, cost-07, cost-08, sus-02, sus-05 under https://docs.aws.amazon.com/wellarchitected/latest/framework/ (V)
- DR strategies: https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_planning_for_recovery_disaster_recovery.html (S)
- Reference repos: ship-it-safely `infra/terraform/bootstrap/locals.tf`, `oidc.tf`, ADR 0007 (S2, S29), ADR 0010 T8, ADR 0011; ship-it-serverless ADR 0012, ADR 0013

## Build briefs

### backend-dev (owns `intake/**`)

Files to create:

| File | Content |
|---|---|
| `intake/schema/platform.schema.json` | M1, M2, Z2, Z4 subset only |
| `intake/sis_intake/__init__.py`, `yamlsubset.py`, `schema.py`, `rules.py`, `validate.py` | Z4 to Z6; stdlib, 3.9-compatible syntax, no `match`, no PEP 604 at runtime |
| `intake/rules/questions.json`, `compat.json`, `rules.json`, `defaults.json` | Z7, M4, table D, V01 to V18 |
| `intake/examples/valid/ship-it-safely.yaml` | ecs-fargate, alb, x86_64, dev and prod `rolling` + `ecs-native` + `rollback: health`, prod `promote_from: dev`, budget 20 (expect warnings V06, V16, no errors) |
| `intake/examples/valid/ship-it-serverless.yaml` | As in the M example |
| `intake/examples/valid/minimal.yaml` | One env, defaults only |
| `intake/examples/invalid/*.yaml` | One file per error rule, first line `# expect: Vnn` (V01, V02, V03, V04, V05, V08, V09, V10 using `123456789012`, V11, V12), plus `unknown-key.yaml` (`# expect: SCHEMA`), `anchor.yaml` and `flow-nested.yaml` (`# expect: PARSE`) |
| `intake/tests/test_yamlsubset.py`, `test_schema.py`, `test_rules.py`, `test_examples.py`, `test_cli.py`, `test_catalog.py` | Below |
| `intake/.claude-plugin/plugin.json`, `intake/skills/intake/SKILL.md`, `intake/agents/intake-interviewer.md` | Z8; version `0.1.0`; no em-dashes |
| `intake/README.md` | Subset spec, CLI, rule table generated from `rules.json` by a test-checked script |

Tests first (red before code):

1. The subset loader rejects anchors, tags, multi-docs and nested flow collections with line numbers. It equals
   `yaml.safe_load` on every example (skipped without PyYAML).
2. The schema interpreter: each supported keyword passes and fails once; an unknown keyword in the schema fails the
   test.
3. Each rule V01 to V18 has a passing case and a failing case built in memory.
4. Every `invalid/*.yaml` yields exactly its `# expect:` ID as an error; every `valid/*.yaml` has 0 errors.
5. `test_catalog`: `rules.json` IDs equal the predicate registry; every rule has pillars and `wa_refs`; every
   `questions.json` group has pillars; `compat.json` engines resolve per M3.
6. CLI exit codes 0, 1 and 2; `--json` output is valid JSON with the Z6 keys.

Done: `python3 -m unittest discover -s intake/tests -t intake` green on 3.13 and on the floor version; ruff and mypy
(strict) clean on `intake/`; no third-party import outside tests.

### devops-engineer (owns `.github/**`, `.claude-plugin/**`, `Makefile`, `.pre-commit-config.yaml`, `pyproject.toml`, `mise.toml`, `scripts/**`)

Files to create:

| File | Content |
|---|---|
| `Makefile` | `help` (default), `venv`, `lint`, `test`, `validate-examples`, `check` (= lint + test + validate-examples). No apply or destroy targets. GNU Make 3.81 compatible |
| `mise.toml` | python 3.13, pre-commit, actionlint, shellcheck, gitleaks; versions looked up at build time |
| `pyproject.toml` | ruff (`target-version = "py39"`, rules as in the labs, `src = ["intake"]`), mypy strict on `intake/sis_intake` and `intake/tests` |
| `.pre-commit-config.yaml` | Revs by SHA with `# frozen:` tags (look up at build time): gitleaks, pre-commit-hooks (check-yaml, check-json, end-of-file-fixer, detect-private-key), the lab `no-aws-account-id` pygrep hook, zizmor, ruff check and format, mypy, `check-jsonschema` (`check-metaschema` on the schema; schema check on `intake/examples/valid/*.yaml`) |
| `scripts/ci/requirements.in`, `requirements.txt`, `venv.sh` | Hash-locked pre-commit and PyYAML (lab pattern) |
| `.github/workflows/ci.yml` | Z9; matrix `python: [3.13, <floor>]` for `make test`; one `check` job aggregates the results for the ruleset |
| `.github/dependabot.yml` | `github-actions` and `pre-commit` (or pip) weekly |
| `.claude-plugin/marketplace.json` | Marketplace `sis-platform`; entry `sis-intake`, source `./intake` |

Tests first: a `scripts/ci/selftest.sh` that fails when a `uses:` line lacks a 40-hex SHA, when a workflow lacks
top-level `permissions: {}`, when a trigger other than `pull_request`, `push` or `workflow_call` appears, or when a
Makefile target name contains `apply` or `destroy`. Wire it into `make lint`.

Done: `make check` green from a clean clone after `mise install`; actionlint and zizmor clean; the CI `check` job
green on the PR; harden-runner in `audit` with its egress list recorded in the PR for Phase 1 `block`; no file
outside the owned paths touched.
