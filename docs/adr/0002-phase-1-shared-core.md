# ADR 0002: Phase 1, the shared core and the contracts Phase 2 builds on

- Status: accepted (owner, 2026-11-04)
- Date: 2026-11-04 (revised 2026-11-04 after the challenger review, see Change log)
- Deciders: owner (accepts), solution-architect (drafts)
- Amends ADR 0001: P4, P9, P13 (T6 deferred), M (adds M6 to M10), O2, O4, O6, O8 (prod plan), A5, B1, B3, B6,
  Amendment A (intake delta D1 to D7 extended to D21). Each amended row says so.

## Context

Phase 0 built the manifest schema, the stdlib validator (V01 to V18), the intake plugin, the repo guard
`scripts/ci/check_repo.py` and CI `check`. Its release `v0.1.0` is pending the Phase 0 checkpoint: no tag exists
yet. Phase 1 extracts the shared core from the two labs. It also settles the contracts Phase 2 builds on: the
resolved plan, the adapter contract, version pinning and OIDC trust. These are the three under-specified seams the
design review found (DP1, DP2, DP3).

Other inputs: Amendment A intake delta D1 to D7 (deferred from Phase 0); design review findings DP4 to DP21; the
Well-Architected review WA1 to WA26 (note of 2026-11-04); the super-board note, board items 1 to 8; the open Medium
and Low items from the Phase 0 verify; the challenger review C1 to C27 of this ADR.

Nothing in Phase 1 calls AWS from Claude. Every check runs offline: unit tests, `terraform test` with mock
providers, actionlint and zizmor. AWS is touched only by the owner at the checkpoint.

### Owner decisions (2026-11-04, defaults accepted)

| # | Decision | Where it lands |
|---|---|---|
| OD1 | DP3: separate `workflow_sha`. Consumers commit `platform.lock`. OIDC trust and `uses:` pin `workflow_sha`; modules and plugins pin `release_sha` | L1 to L4, O9, O10 |
| OD2 | DP1: `platform.yaml` is the only source of release behavior. Validator `--json` emits a versioned resolved plan (M6). Dispatch inputs carry only a SHA or digest. GitHub environment settings hold only account and role identifiers | M6 to M8, O13 |
| OD2a | Refinement (architect): the account ID is stored as an environment **secret**, not a var, so it is masked in public logs. Role ARNs are derived from the M6 role names, so no role variable is needed. The owner can reject this | O13 |
| OD3 | One phase at a time. Each ADR gets a docs PR and each build a PR stacked on it. The autopilot section of CLAUDE.md is removed (done in this docs branch). The owner merges | Build briefs |
| OD4 | Board items are built directly in sis-platform (amends B3: no wait for serverless board PRs). The guard is still copied from serverless `main` per B3 step 4. One card per phase and per checkpoint. Only the orchestrator moves cards, via `board.py` and `gh project item-*`. Borrowed code is credited. No super-board install | B9 to B15, S1 |
| OD5 | Nothing for English for Devs before the platform is complete (P14) | X table |
| OD6 | Commit email unchanged | n/a |

### Facts checked

ADR 0001 F1 to F16 still hold. F3 is still (C).

| # | Fact | Mark |
|---|---|---|
| F17 | The `job` context has `job.workflow_ref`, `job.workflow_sha`, `job.workflow_repository` (`owner/repo` of the file that defines the job) and `job.workflow_file_path`. In a reusable workflow they describe the reusable file, not the caller. They are not available on GHES | V |
| F18 | In a called workflow the `github` context is always the caller's. `GITHUB_TOKEN` permissions can only be downgraded by the called workflow | V |
| F19 | The OIDC token has a `job_workflow_sha` claim. GitHub docs show no example of `job_workflow_ref` for a SHA-pinned call, so F3 stays (C) until O12 step 4a | V, C |
| F20 | The docs do not say which repository the `vars` context comes from in a called workflow | C (design avoids depending on it) |
| F21 | A marketplace source (`github`, `git`) accepts `ref` (branch or tag) and `path`, but **no `sha`**. Plugin sources (`github`, `url`, `git-subdir`) accept `ref` and `sha`. A relative plugin source resolves from the marketplace root of the fetched marketplace | V |
| F22 | Skill frontmatter `disable-model-invocation: true` stops Claude from invoking the skill. `allowed-tools` pre-approves tools but restricts nothing | V |
| F23 | Terraform test mocking exists from v1.7.0. `override_during` takes `plan` or `apply` (default `apply`). `mock_data` takes `defaults` | V |
| F24 | Public reusable workflows can be referenced by SHA, tag or branch. A rerun of failed jobs uses the first attempt's SHA | V |
| F25 | An IAM OIDC provider ARN is `oidc-provider/<host>`, so an account holds one GitHub provider | S |
| F26 | `gh project item-edit` takes `--id`, `--project-id`, `--field-id` and `--single-select-option-id`. The required token scope is not stated | V flags, C scope |
| F27 | Well-Architected IDs opened in this pass: SEC01-BP06, OPS05-BP01, OPS05-BP04, REL08-BP05, SUS06-BP01, SUS04-BP03 | V |
| F28 | The context availability table lists `job` for `jobs.<job_id>.steps.with` and `steps.run`, so `ref: ${{ job.workflow_sha }}` on a checkout step is valid | V |
| F29 | To use an environment secret in a reusable workflow, the reusable job sets `environment`; the caller job cannot use `environment` and must still pass the secret, by name even if it exists only in the environment. A secret the caller does not pass resolves to an empty string. The docs do not say whether this holds when the caller is in another owner | V, C (cross-owner) |
| F30 | On GitHub Free, Pro and Team, environment required reviewers and wait timers are only available for public repositories. Environment secrets in a private repo need Pro, Team or Enterprise. One required reviewer approval is enough. "Prevent self-reviews" is an opt-in setting | V |
| F31 | Fine-grained personal access tokens list a Projects permission only at organization level; no user-level Projects permission is listed. GraphQL Projects v2 access with a fine-grained token is not documented. A classic token with the `project` scope works with `gh project` | V (REST page), S (`project` scope), C |
| F32 | A commit pushed to any fork is reachable by SHA through the parent repository's network ("impostor commit"), so a SHA alone does not prove the commit is on sis-platform `main` | S |
| F33 | `actions/checkout` supports `sparse-checkout` with cone mode off | S, re-read at build |
| F34 | ECR tag mutability with exclusion filters (some tags mutable on an otherwise immutable repo) | S, C in Phase 2 |

## Decision

### P15. Escape-hatch ladder (DP21, amends P2)

| # | Decision |
|---|---|
| P15 | A project leaves the paved road in this order, and only as far as it needs: (1) a module input override; (2) extra Terraform in its own root next to the platform module; (3) caller jobs before or after the reusable workflow; (4) later, `runtime.kind` with a project adapter that passes conformance (K7). No `x-` keys in `platform.yaml`. A hatch used by two projects becomes a platform feature |

### M. Resolved plan (amends M; DP1, DP9, DP10, DP13; WA1, WA5, WA24)

| # | Decision |
|---|---|
| M6 | `validate.py FILE --json` emits a complete resolved plan. Top level: `format_version: 1`, `platform_version`, `schema_version`, `context`, `valid`, `findings[]`, `project{name,prefix,owner}`, `runtime{kind,family,arch,front_door}`, `workload{port,health_path,peak_rps,p95_ms}`, `envs{}`. Per env: `tier`, `account` (label), `region`, `prefix`, `delivery`, `promote_from`, `strategy`, `steps`, `bake_minutes`, `probes`, `rollback`, `engine`, `deploy_role_profile`, `roles{plan,apply,deploy}` (names, never ARNs), `budget_monthly_usd`, `data_class`, `observability{}` (M10), `built{runtime,engine,delivery,profile}`. `PARSE` and `SCHEMA` are documented finding IDs. Adding a key is a minor change; renaming or removing one bumps `format_version` and is a platform major bump |
| M7 | Workflows and env roots consume only M6. `validate.py FILE --emit tfvars --env <e>` prints `{"platform": {...env slice...}}`. CI writes it under `$RUNNER_TEMP` and passes `-var-file`; it never lands in the repo (a `*.tfvars.json` path is also blocked by the guard). `project.env` in consumers is checked against `project.prefix`. Dispatch inputs are only `sha` (40-hex) or `digest` (`sha256:` + 64 hex) |
| M8 | `--context lint` is the default (V17 is a warning). `--context deploy` turns V17 into an error for an unbuilt runtime, engine, delivery or profile. `reusable-release.yml` (Phase 2) runs `deploy` and stops with exit 2 on a V17 error. The Terraform workflows run `lint`, because a root can be planned before its adapter exists |
| M9 | Capabilities as data in `compat.json` per runtime: `family`, `gradual_needs_alb`, `gitops` (replaces the dead `gitops` string), `fixed_monthly_usd`, `two_versions_live`, `env_flags`, `alarms[]` (M10), `built{runtime, engines{}, delivery{}, profiles{}}`. Predicates read data, never `startswith("lambda")` or "73 USD". A test asserts schema `runtime.kind` enum = compat keys = defaults keys. In Phase 1 every `built` flag is false |
| M10 | Observability contract (WA1, WA24). Per env `observability{slo{availability_pct,p95_ms}, alarms[], log_retention_days, notify}`. `alarms[]` is the runtime's alarm set from `compat.json` (for Lambda web: 5xx rate including app 5xx, p95 latency, throttles, probe failures), named `<prefix>-<env>-<alarm>`. `log_retention_days` defaults from `defaults.json`: 14 nonprod, 90 prod, 365 for `regulated`. `notify` is the SNS topic name the bootstrap creates (T7). Runtime modules build the alarms in Phase 2; the adapter reads the names from the plan (K2) |

### D. Intake delta (amends Amendment A; backend-dev)

D1 to D7 land as written in ADR 0001 Amendment A.

| # | Change | Test |
|---|---|---|
| D8 | `envs.<e>.tier: prod \| nonprod` is required (DP8). V11, V16 and V18 read `tier`, not the env name | `prod` named env with `tier: nonprod` gives no V11; renamed prod env with `tier: prod` does |
| D9 | V20 (E, REL and SEC; REL08-BP04, SEC01-BP01). `promote_from` names an existing, different env. The promote graph is acyclic. Account labels are distinct across envs | `invalid/promote-unknown.yaml`, `promote-cycle.yaml`, `shared-account.yaml`, each `# expect: V20` |
| D10 | V21 (E, OPS). An env flag must be in its runtime's `env_flags` (`fargate_spot` on ecs-fargate only, `scale_to_zero` per data) | `invalid/flag-wrong-runtime.yaml` |
| D11 | `built` per engine, delivery and profile, plus `--context deploy` (M8). DP19's flag-equals-directory test comes with the first adapter in Phase 2 | CLI exit 1 under `deploy`, 0 under `lint` |
| D12 | `@rule("Vnn")` decorator registry. Rule parameters are passed separately from `Ctx` (DP15) | Catalog test still 1:1 |
| D13 | `minProperties` joins the Z4 keyword subset. The empty-`envs` check moves from code into the schema (DP14) | Keyword guard test updated |
| D14 | `validate.py -` reads stdin. The intake agent drops its temp file and its Bash is narrowed to the validator (DP12, Phase 0 security item) | Agent frontmatter test |
| D15 | V10 also scans the raw text, so comments are covered (Phase 0 e2e item) | 12-digit number in a comment gives V10 |
| D16 | `--json` always prints JSON, including a `PARSE` finding for an unreadable file (exit 2) | CLI test |
| D17 | `plugin.json` gets `author`. A test asserts `plugin.json` version = `sis_intake.__version__` | Test |
| D18 | Schema (WA5, WA20): `project.owner` (GitHub login or team handle, never an email) and `budget.monthly_usd` are required | `invalid/no-budget.yaml`, `invalid/no-owner.yaml` (`SCHEMA`) |
| D19 | V22 (E, SEC; SEC07-BP01, SEC08-BP01; WA10): a `tier: prod` env needs `compliance.data_class`; `data_class: regulated` needs `kms_cmk: true` | `invalid/prod-no-data-class.yaml`, `invalid/regulated-no-cmk.yaml` |
| D20 | V23 (E, REL; REL13-BP01; WA13): a `tier: prod` env needs `dr.rto_minutes` and `dr.rpo_minutes`. V24 (E, PERF; PERF05-BP01; WA18): a `tier: prod` env needs `workload.peak_rps` and `workload.p95_ms` (both optional for nonprod) | One fail file per rule |
| D21 | V25 (E, SUS and SEC; SUS01-BP01; WA25): `envs.<e>.region` must be in `defaults.json` `allowed_regions` (Phase 1: `ap-southeast-1`). `wa_refs` in `rules.json` are corrected to BP-level IDs per the WA note | `invalid/region-not-allowed.yaml`; `test_catalog` asserts `^[A-Z]{3,4}[0-9]{2}-BP[0-9]{2}$` |

### K. Adapter contract v1, specification only (amends P4 and A2; DP2; built in Phase 2)

Phase 1 writes `adapters/CONTRACT.md`, `adapters/adapter.schema.json` and `adapters/result.schema.json` (Z4 keyword
subset, metaschema-checked) in sub-PR 1g. It writes no adapter.

| # | Decision |
|---|---|
| K1 | Verbs stay `deploy`, `verify`, `rollback` and `status`, each an executable `adapters/<kind>/<verb>`. Rollback is still "deploy an earlier digest" (P4) |
| K2 | Inputs are env vars: `SIS_CONTRACT_VERSION=1`, `SIS_PLAN` (path to the M6 JSON), `SIS_ENV`, `SIS_DIGEST`, `SIS_SHA`, `SIS_RELEASE_ID`, `SIS_PREV_DIGEST` (rollback only). The adapter reads strategy, steps, bake, probes, rollback, prefix and the M10 alarm names from the plan only. A2's `PREFIX` and `STRATEGY` are folded into the plan |
| K3 | Output is one JSON line: `contract_version`, `verb`, `env`, `release_id`, `digest`, `sha`, `live_ref`, `candidate_ref`, `traffic{candidate_percent}`, `state`, `endpoint`, `message`. The generic `*_ref` fields replace A2's `version` and `live_version` |
| K4 | `state` is one of `publishing`, `verifying`, `shifting`, `baking`, `succeeded`, `failed`, `rolled_back`. Exit codes: 0 succeeded, 1 failed, 2 refused (precondition or policy), 3 in progress |
| K5 | `release_id = <env>-<first 12 hex of the digest>`. `deploy` is idempotent per (env, digest): a rerun resumes from `status`. One release in flight per env (concurrency group). Exit 3 lets a workflow resume a long bake in a later job |
| K6 | `adapters/<kind>/adapter.json` declares `contract_version`, `kind`, `strategies`, `engines`, `deploy_role_profile`, `egress_hosts` per verb (literal templates with `{region}` only) and `max_step_seconds` |
| K7 | Conformance suite `adapters/conformance/` runs every verb against a stub on every PR (Phase 2) |
| K8 | A change to `contract_version` is a platform major bump (P8) |

### L. Versioning, lock and the P9 check (amends P8, P9, B1; DP3, DP11, DP20)

| # | Decision |
|---|---|
| L1 | A consumer commits `platform.lock` as JSON (stdlib-readable and readable by Terraform `jsondecode`): `lock_version: 1`, `version` (`vX.Y.Z`), `release_sha`, `workflow_sha`, `trusted_workflow_shas` (1 to 2 distinct 40-hex values, must contain `workflow_sha`). The last two fields extend OD1, so the N and N-1 trust list is committed and checkable instead of sitting in gitignored tfvars |
| L2 | The workflow closure is listed in `scripts/release/closure.txt` as `:(glob)` pathspecs: `closure.txt` itself, `.github/workflows/reusable-*.yml`, every script those workflows run or source (`scripts/platform/**`, `scripts/tf/**`, `scripts/aws/**`, `scripts/lib.sh`), the validator runtime (`intake/sis_intake/**`, `intake/schema/**`, `intake/rules/{compat,defaults,rules}.json`) and, from Phase 2, `adapters/**`. `workflow_sha = git log -1 --format=%H <release_sha> -- <closure pathspecs>`. History on `main` is linear (squash merges only, ruleset), so the value is well defined. It is deterministic, so it is never stored in the commit it names. devops-engineer writes `closure.txt` and covers backend-dev's intake paths |
| L3 | P9 check `scripts/platform/check_lock.py` (stdlib plus PyYAML for workflow files). Offline it checks: the lock schema; `platform.yaml` `platform.version` = lock `version`; every `uses: trungleviet-agilityio/sis-platform/...@<x> # <v>` (any YAML form) has `x = workflow_sha` and `v = version`; every `git::https://github.com/trungleviet-agilityio/sis-platform.git//modules/<m>?ref=<x>` has `x = release_sha` and no other remote module source exists; `.claude/settings.json` pins marketplace `sis-platform` to `ref = version`. With `--remote` (anonymous blobless clone of the public repo) it also checks: tag `version` resolves to `release_sha`; `release_sha` is an ancestor of the sis-platform `main` tip; L2 recomputes to `workflow_sha`; and **for every SHA in `trusted_workflow_shas`**: (a) it is an ancestor of the `main` tip (F32), (b) it equals the L2 `workflow_sha` of some released `v*` tag, (c) its tree has no `.github/workflows/reusable-release.yml` while the constant `DEPLOY_TRUST_ALLOWED` is false (Phase 1; the Phase 2 ADR flips it), so the deploy role stays inert |
| L4 | Plugins (DP11; F21 means a marketplace cannot be pinned by SHA). Consumers declare `extraKnownMarketplaces.sis-platform.source = {source: github, repo: trungleviet-agilityio/sis-platform, ref: <version>}`. `sis-intake` (`./intake`) and `sis-team` (`./plugins/sis-team`) are relative entries, so they follow the tag. Integrity comes from the immutable tag ruleset plus the L3 `--remote` tag-to-SHA check. The release check `scripts/release/check_release.py` (sub-PR 1f-1) asserts every `plugin.json` version = tag = `__version__` |
| L5 | Phase 1 releases `v0.2.0` (breaking in 0.x: `tier`, `owner` and `budget` are required, JSON shape changes). `schema_version` stays 1, because no consumer pinned `v0.1.0`. Accepted |
| L6 | DP20: `intake/rules/*.json` and the generated README table are authoritative over the copies in ADR 0001 |
| L7 | Trust moves are batched (C4). `check_release.py --tag <v> --sha <s>` prints `workflow_sha`, whether it moved since the previous tag, and the closure paths that changed. A patch tag (`vX.Y.Z`, Z > 0) must not move `workflow_sha`; it fails otherwise. So a trust move needs a minor release, and intake data fixes wait for the next minor unless they are urgent (then the minor is cut early). The README rule table is outside the closure |

Options for where the N and N-1 trust list lives (L1):

| Option | Pros | Cons |
|---|---|---|
| A. In `platform.lock` (chosen) | Committed and reviewed; the P9 check sees it; the bootstrap root reads it with `jsondecode` | Two extra lock fields beyond OD1 |
| B. Gitignored tfvars (lab) | No lock change | Invisible to checks (the DP3 finding) |
| C. Lock holds `workflow_sha` plus `previous_workflow_sha` | Smaller | The rollout step "add new before bump" cannot be expressed |

Options for where the validator runs (L2):

| Option | Pros | Cons |
|---|---|---|
| A. Inside the closure, run by the reusable workflow at `workflow_sha` (chosen) | One source; nothing generated is committed; the caller cannot pass a hand-made plan | A rule-data fix moves `workflow_sha`, so trust needs a re-apply; limited to one move per minor by L7 (accepted) |
| B. Consumer commits the resolved plan, plus a drift check | Intake fixes never touch trust | A generated file in every repo; one more check |
| C. Caller job computes the plan and passes it as an input | Simple | A steerable channel into the trusted run (rejected) |

Options for how often trust may move (L7):

| Option | Pros | Cons |
|---|---|---|
| A. Patch never moves `workflow_sha`; a move needs a minor (chosen) | Predictable re-apply cadence; machine-checked at release | An urgent rule fix costs a minor bump |
| B. Print only, no rule | No friction | Every release can need a re-apply per account |
| C. Move the rule data out of the closure | Fewest trust moves | The trusted run would read untrusted rule data (rejected) |

### O. OIDC trust (amends O2, O4, O6, O8; DP3, DP4)

| # | Decision |
|---|---|
| O9 | Amends O2. Apply trusts `trungleviet-agilityio/sis-platform/.github/workflows/reusable-terraform-apply.yml@<sha>` and deploy trusts `.../reusable-release.yml@<sha>`, for each `<sha>` in `trusted_workflow_shas`. Both use StringEquals. The deploy file does not exist until Phase 2, and L3 (c) refuses a trusted SHA that contains it, so in Phase 1 the deploy role is inert by design. The value template is held in one Terraform local (outside the closure, so fixing it is a patch); O12 step 4a confirms it (F3, F19) |
| O10 | Amends O4. A bootstrap re-apply is needed only when `workflow_sha` changes (at most once per minor, L7). Rollout: PR 1 adds the new SHA to `trusted_workflow_shas` (P9 still green, including L3 `--remote`); the owner re-applies bootstrap in dev, then prod; PR 2 bumps `version`, `release_sha`, `workflow_sha` and `uses:`. The next workflow change drops the oldest SHA. When `workflow_sha` does not move, a bump is only PR 2 |
| O11 | DP4. A reusable workflow checks out sis-platform with `repository: trungleviet-agilityio/sis-platform`, `ref: ${{ job.workflow_sha }}` (F28), `path: .platform`, `persist-credentials: false` and `sparse-checkout` of exactly the `closure.txt` paths, cone mode off (F33), so a file missing from the closure fails closed. A first step asserts `job.workflow_repository == 'trungleviet-agilityio/sis-platform'`, that `job.workflow_file_path` starts with `.github/workflows/reusable-` (F17), and that `job.workflow_sha` is in the caller's committed `trusted_workflow_shas`. Scripts are always run from `.platform/` |
| O12 | O5 smoke gate, in three steps (checkpoint 4a, 7, 8). `reusable-oidc-smoke.yml`, called by SHA from the canary repo. **4a claims only, before any account exists**: on `main` with `environment: dev`, it prints the non-secret claims `job_workflow_ref`, `job_workflow_sha`, `sub`, `ref`, `repository_id` (never the token) plus `job.workflow_sha`, fails unless `job_workflow_sha = job.workflow_sha = workflow_sha`, and asserts that the passed `AWS_ACCOUNT_ID` is non-empty without printing it (F29 cross-owner check). No AWS call. **7 negative**: the same caller (`main`, `environment: dev`, so `sub`, `ref` and `repository_id` all match) asks the smoke workflow to assume the dev apply and deploy roles and requires an explicit AccessDenied; only the file in `job_workflow_ref` differs. **8 positive**: the real dev and prod applies are the only proof that AWS accepts the value. If 4a shows a format other than `@<sha>`, the O9 local pins the exact observed string in a patch release before any bootstrap; never widen to a wildcard |
| O13 | Amends O6 (OD2a; F29). Every reusable Terraform workflow declares one secret, `AWS_ACCOUNT_ID` (required). Apply and deploy jobs set `environment`, and the caller passes `AWS_ACCOUNT_ID: ${{ secrets.AWS_ACCOUNT_ID }}`, which resolves to the environment secret. Plan callers pass `AWS_ACCOUNT_ID: ${{ secrets.AWS_ACCOUNT_ID_<ENV> }}` from repo secrets. Fallback, defined now: if 4a shows the environment secret does not resolve cross-owner, apply callers also pass the repo secret `AWS_ACCOUNT_ID_<ENV>`; the reusable interface does not change, so the fallback is not a major bump. A first step fails on an empty value. No `secrets: inherit`. Role ARNs are `arn:aws:iam::<id>:role/<M6 role name>`. No other variable or secret may hold release behavior; A12 enforces it |
| O14 | Amends O8. O1 is unchanged. The dev (nonprod) plan role keeps the caller's `pull_request` sub (F2, F18) and pins no file. The prod plan role trusts only `ref:refs/heads/main` or `environment:prod` subjects, so a PR never plans prod. A same-repo PR author can run code as the nonprod plan role and read that env's state: **accepted**, limited by the T4 denies. Fork PRs get no OIDC token (C at checkpoint 8) |

Options for the canary repo visibility (checkpoint 3, F30):

| Option | Pros | Cons |
|---|---|---|
| A. Public (chosen) | Required reviewers, branch policies and environment secrets work on every plan; same model as sis-platform | Workflow logs are public; relies on masking, V10 and the guard (already required for sis-platform) |
| B. Private on GitHub Free or Pro | Logs private | No required reviewers (F30), so the C2 gate cannot exist; environment secrets need Pro |
| C. Private on Enterprise | All features | Paid plan for a two-account canary |

### T. Terraform: `account-bootstrap` and profiles (amends P1, A5, A6; DP5)

| # | Decision |
|---|---|
| T1 | `modules/account-bootstrap` is extracted from the labs' `infra/terraform/bootstrap` (credited in file headers). No `provider` or `backend` blocks; the consumer root `infra/bootstrap` owns them, with `allowed_account_ids` and `default_tags` (`Project`, `Env`, `Tier`, `Owner`, `ManagedBy`, `Platform`, `PlatformVersion`; COST03, OPS02-BP01, WA5). Terraform and AWS provider versions are pinned at build time (labs: `>= 1.11` for `use_lockfile`, AWS `~> 6.x` for `bucket_namespace`) |
| T2 | OIDC provider: `create_oidc_provider` (default true) or a data lookup when the account is shared, because an account holds one GitHub provider (F25). The created provider has `lifecycle { prevent_destroy = true }`. No thumbprint list |
| T3 | State bucket as lab B8: account-regional namespace, versioning, SSE-S3 with SSE-C blocked, TLS-only policy, public access block, owner enforced, lifecycle on noncurrent versions. Keys `envs/<env>/terraform.tfstate` and `bootstrap/` (the latter denied to CI, G5). The bucket name contains the account ID, so it is never committed: locally it comes from the gitignored `accounts/<env>.backend.hcl` via `-backend-config`; CI composes it at run time from `AWS_ACCOUNT_ID` and M6 and passes `-backend-config` |
| T4 | Roles `<prefix>-<env>-gha-{plan,apply,deploy}`, 3600 s sessions. Trust per O1, O9 and O14. Plan role (WA7): ReadOnlyAccess plus explicit denies on `secretsmanager:GetSecretValue`, on `kms:Decrypt` for every key (state is SSE-S3, so plan needs none; this also blocks SecureString reads), on S3 reads outside the state keys, and on every action that is not a read (`NotAction` list of `Get*`, `List*`, `Describe*`, `Head*`, `sts:GetCallerIdentity`, plus `s3:PutObject` and `s3:DeleteObject` on the env's `.tflock` key only). Apply and deploy roles: state access plus composed policies (T8). Guardrails G1 to G6 attached to all three. tftest asserts each deny. Missing reads surface in the A7 check |
| T5 | ECR (A5, WA14, WA24): one repo `<prefix>-<env>-app`, IMMUTABLE tags, scan on push, AES256. Lifecycle: untagged images expire after 14 days; tagged images keep the newest 20 (nonprod) or 50 (prod). In Phase 2 the adapter marks `live` and `prev` so they never expire (F34, C); until then no image is live. A KMS CMK (P13) is out of Phase 1. Changing encryption later replaces the repository; accepted |
| T6 | Promotion (P13) is **deferred to Phase 2**. Phase 1 has no promoting user, and a repository policy that names a role that does not exist yet fails. Phase 2 grants the target account root principal with `ArnEquals aws:PrincipalArn` on the target deploy role |
| T7 | Budget from M6 `budget_monthly_usd` (each account gets the project ceiling) with actual and forecast alerts at 80 and 100 percent to the `notify` topic (WA20). A Cost Anomaly Detection monitor (`create_anomaly_monitor`, default true; free, S). The SNS email topic (`notify`, M10); the email is a sensitive tfvar. Detective baseline (WA6): `create_trail` default **true** (multi-region, log file validation, S3 bucket in the account with lifecycle; first copy of management events free, S); an IAM Access Analyzer external access analyzer (default on; free, S); `enable_guardduty` default **false** (30-day trial, then billed by volume, S; the owner turns it on per account). An EventBridge rule on `AssumeRoleWithWebIdentity` errors or subjects outside the trust. When `org-baseline` adds an organization trail, the account trail is removed (accepted, closes in `org-baseline`) |
| T8 | Composition (DP5). The bootstrap takes `apply_policy_json`, `deploy_policy_json` and `ecr_repository_policy_json` (null by default). The consumer root wires them from `modules/deploy-profile-<profile>` and `modules/apply-profile-<kind>` (Phase 2) chosen by M6. A precondition keeps only cheap structural checks after normalizing `Statement` and `Action` to lists: no `Allow` with `*` or `iam:*` actions, no `NotAction`, no `NotResource`. Another precondition asserts `var.platform.deploy_role_profile` equals the wired profile name. The full lint lives in one place, `scripts/tf/policy.py` (T11). `modules/PROFILES.md` specifies the interface |
| T9 | Tests first, in `modules/account-bootstrap/tests/*.tftest.hcl` with `mock_provider` (F23), ported from the labs: trust (exact values, 1 to 2 SHAs, StringEquals), iam, plan role denies, guardrails, state, ecr lifecycle, budget and anomaly monitor, monitoring (trail, analyzer, GuardDuty flag), boundary, validation, composition preconditions. The only fake account ID is `123456789012` |
| T10 | Bootstrap is never applied in CI (lab E4). The owner's first apply uses a gitignored `backend_override.tf` (local), then `init -migrate-state` to `bootstrap/terraform.tfstate` (lab B10) |
| T11 | Privilege escalation (C7, C8). The bootstrap creates `<prefix>-<env>-workload-boundary` (lab `ship-it-safely/infra/terraform/bootstrap/iam_ecs_boundary.tf` pattern) and outputs `workload_boundary_arn`. `scripts/tf/policy.py` is the only full linter. It reads IAM documents from fixture JSON (Phase 1, `make tf-check`) or from `terraform show -json` (the reusable plan job). It fails: `Allow` `*` actions, `iam:*`, `sts:AssumeRole*`, `NotAction`, `NotResource`; `Resource: "*"` outside the allowlist of actions with no resource-level support; `iam:CreateRole`, `iam:PutRolePolicy`, `iam:AttachRolePolicy` or `iam:PutRolePermissionsBoundary` without `iam:PermissionsBoundary` equal to the boundary ARN; `iam:PassRole` without `iam:PassedToService`; any write to the boundary policy itself. `PROFILES.md` fixes this interface now |

Options for profile composition (T8):

| Option | Pros | Cons |
|---|---|---|
| A. Root composes, bootstrap prechecks structure, one full linter (chosen) | Bootstrap stays a small facade; one lint to maintain; fixtures test it in Phase 1; new runtime = new module | One more module block in each consumer root (template) |
| B. Count-gated profile modules inside the bootstrap | One call site | God module (DP5); every runtime edits the bootstrap |
| C. Full lint in both HCL and `policy.py` | Fails early in plan | Two linters drift; HCL lint of string or list forms is fragile (C8) |

Options for the detective baseline (T7, WA6):

| Option | Pros | Cons |
|---|---|---|
| A. Trail and analyzer on, GuardDuty flag off (chosen) | Records every role use from day one; A7 reads that trail; near-zero cost | No threat detection until the owner turns GuardDuty on (accepted) |
| B. All on | Full detection | GuardDuty cost against a 20 USD budget after the trial |
| C. Wait for `org-baseline` | No duplicate trail later | Real roles in real accounts with no record (WA6 High) |

### W. Reusable workflows (amends O7, P1; DP6)

| # | Decision |
|---|---|
| W1 | Paths frozen from now (trust, P8): `reusable-terraform-plan.yml`, `reusable-terraform-apply.yml`, `reusable-platform-check.yml`, `reusable-oidc-smoke.yml`; Phase 2: `reusable-release.yml` |
| W2 | Each Terraform workflow starts with a `resolve` job without credentials: O11 checkout, validator (`lint`), M7 tfvars, and outputs `family`. One credentialed job per runtime family, gated by `needs.resolve.outputs.family == '<literal>'`, with literal hosts (A9). Phase 1 ships the `lambda` family (hosts ported from serverless). Other families come with their runtime |
| W3 | Plan: plan role, `policy.py` over `terraform show -json` (T11), account-free summary (`plan-summary.sh`, `assert-no-account-id.sh`), plan file deleted, sticky comment job with `pull-requests: write` and no AWS. Its scripts come from `.platform` at `workflow_sha`, so the lab's base-SHA workaround is not needed |
| W4 | Apply: `environment: ${{ inputs.env }}`, apply role, `concurrency: tf-<env>` with `cancel-in-progress: false` |
| W5 | `reusable-platform-check.yml` runs L3 with `--remote` and no credentials (`audit` egress: `github.com` only). Consumers require it on every PR and run it weekly on a schedule |
| W6 | Callers pass the `env` input and the one named secret `AWS_ACCOUNT_ID` (O13), with `permissions: {contents: read, id-token: write}` (plus `pull-requests: write` for plan). The caller job has no `environment` key (F29) |
| W7 | Release skeleton, specified now and built in Phase 2: `resolve` (`--context deploy`) then a per-family `release-<family>` job that runs `deploy` until exit 0 or 1 (exit 3 continues in a `resume` job), then `verify`, then `report`. Inputs: `env`, `digest`, `sha`. Project hooks are caller jobs before and after (DP6) |

### H. Repo guard hardening (DP16, Phase 0 security items)

| # | Decision |
|---|---|
| H1 | `check_repo.py` reads `uses:` from parsed YAML (flow style included) in every `.yml` and `.yaml` under `.github/` and `examples/consumer/.github/`. Every SHA pin needs a `# vX.Y.Z` comment |
| H2 | No `write-all` or `read-all` at any level. `id-token: write` only on a job whose steps assume a role or print OIDC claims |
| H3 | Port `harden_runner_policy.py` (lab ADR 0007 S45, A9), adapted: account hosts only from `secrets.AWS_ACCOUNT_ID*`; region only from M6 resolve outputs or literals; W2 family gating required on credentialed reusable jobs |
| H4 | `reusable-*.yml` declare `workflow_call` only. Profile `consumer` (for `examples/consumer`) also allows `workflow_dispatch` with inputs named only `env` (choice), `sha` or `digest` (OD2) |
| H5 | A checkout of sis-platform must use `ref: ${{ job.workflow_sha }}` and `sparse-checkout` (O11) |
| H6 | Every `.platform/<path>` referenced in a reusable file is covered by `closure.txt` (L2). The closure test runs on a fixture git repo with `:(glob)` pathspecs, a renamed file and a file sourced by a script |
| H7 | `no-aws-account-id`: narrow the exclude to `intake/examples/invalid/account-id.yaml`; also match `1234-5678-9012`; hash-lock `types-PyYAML` respecting the 7-day cooldown |
| H8 | CI concurrency cancels in progress only for `pull_request`, never `main` pushes |
| H9 | Terraform tooling (built in 1e): `mise.toml` adds terraform, tflint and terraform-docs; `make tf-check` runs fmt, validate, test, tflint, the README check and `scripts/tf/policy.py` on fixtures; `scripts/tf/resolved-sources.sh` allows local sources or sis-platform at `release_sha` only. `.claude/rules/terraform.md` (orchestrator, C2) |
| H10 | WA3: a job that has `id-token: write` or an `environment` must sit under a concurrency group with `cancel-in-progress: false` |

### S. sis-team plugin, guard and skills (amends B1, B3, B6, B8; A14, A15, C4)

| # | Decision |
|---|---|
| S1 | Commit 1 copies `plugins/sis-team` verbatim from serverless `main` at a recorded SHA (eb212c9 seen on 2026-11-04; re-read at build time). The allowed diff in that commit is `plugin.json` and README paths only, shown by `git diff --no-index` in the PR body. Every later change is its own commit |
| S2 | Guard additions, credited to super-board (MIT): `Edit`/`Write` outside the repo or the agent's worktree; `rm -r` outside the repo root; credential literals in a command (`AKIA`, `ghp_`, `github_pat_`, PEM header); `gh project item-delete`; a Bash command that reads the `sis-board-token` Keychain item or sets `GH_TOKEN`/`GITHUB_TOKEN` inline (B16). G1 to G7 and A14 are kept. Stdlib, system `python3` 3.9 |
| S3 | `test_guard.py` asserts the message for every blocked and allowed form. It runs in `make test` on 3.9 and 3.13 |
| S4 | Skills: keep plan, run, close, review, team, diagram. Rewrite the lab-specific descriptions and paths so agents read ownership from the repo's CLAUDE.md. Add `board` (`status` read-only; `sync` has `disable-model-invocation: true`). `pin-versions`, `release-prep`, `github-settings-check` and `checkpoint-commands` are Backlog cards, not Phase 1 (C27); `check_release.py` and `check-settings.sh` cover the need |
| S5 | Round-2 reviews list every prior finding first as fixed, open or n/a. The security reviewer adopts a high-confidence, false-positive filter rubric (credited) |
| S6 | Marketplace entry `sis-team` source `./plugins/sis-team` (L4) |
| S7 | sis-platform's own sessions enable `sis-team@sis-platform` from the `github` marketplace pinned to the last tag, so a branch cannot weaken the guard that runs on it. Until `v0.2.0` exists, the deny list stays the only guard (accepted, as in ADR 0001 Q2) |
| S8 | Ownership: devops-engineer owns `plugins/**` (code and markdown), `examples/**` outside `intake/`, `adapters/**` and `scripts/**`; backend-dev owns `intake/**` including `intake/examples/**`. The orchestrator owns `.claude/settings.json`, `.claude/rules/terraform.md`, `project.env`, `docs/**` and the CLAUDE.md agent table (adds `plugins/**` and `examples/**` to devops-engineer) |

Options for which plugin copy sis-platform's own sessions load (S7):

| Option | Pros | Cons |
|---|---|---|
| A. Marketplace at the last tag (chosen) | A PR cannot weaken its own guard | Guard fixes apply only after a tag |
| B. `directory` source `.` | Dogfoods HEAD | A branch edits the hook it runs under |
| C. Serverless copy at user scope | Works today | A second copy; drift |

### B. Board (amends B3 to B7; OD4)

| # | Decision |
|---|---|
| B9 | Amends B3. Step 3 is dropped. Board, skills and lifecycle are built in sis-platform. Steps 5 and 6 are unchanged (Phase 2) |
| B10 | One issue and card per phase and per checkpoint (`Kind`: phase, checkpoint, platform-bump, bug). Sub-tickets are a checklist in the issue body |
| B11 | `plugins/sis-team/scripts/board.py` (stdlib) has verbs `status`, `add`, `move`, `comment` and uses only `gh project item-add\|item-edit\|item-list\|field-list\|view` and `gh issue create\|comment` (F26). Never `gh api`. It reads `SIS_BOARD_OWNER` and `SIS_BOARD_PROJECT` from `project.env` and refuses any other project, column or verb. `--dry-run` prints the argv |
| B12 | Only the orchestrator moves cards; subagents never do. `.claude/settings.json` allows only `Bash(python3 *plugins/sis-team/scripts/board.py *)` and denies `gh project delete\|close\|field-delete\|item-delete` |
| B13 | Lifecycle in plan, run and close: Backlog, Planned (`/plan`), Ready (ADR accepted), Building (`/run`), Verify, Needs you (checkpoint), Done (merged or `/close`). Blocked is used only with a reason |
| B14 | The Needs-you template (`references/needs-you-template.md`) has: what, why, exact commands, expected output, what Claude does next, and a readiness checklist (WA4: alarms exist and fired once in a test, a runbook per alarm, rollback rehearsed once in dev; items not yet built say "n/a until Phase 2"). It links the runbooks in `docs/runbooks/`. No secrets or account IDs |
| B15 | B7 platform-bump cards: `close` lists one card per consumer in a dry run |
| B16 | Tokens (C13, F31). `gh project` calls use a separate classic token with only the `project` scope, stored in the Keychain as `sis-board-token`. `board.py` reads it at run time and sets `GH_TOKEN` only in the environment of its own `gh project` subprocess; it is never exported to the shell. `gh issue` calls use the shell's fine-grained git PAT (Issues write). The git PAT never gets `project` scope, Actions write, Administration write or Environments write. The `project` scope reaches every project the owner has; `board.py` refuses all but one (accepted) |

Options for the board token (B16):

| Option | Pros | Cons |
|---|---|---|
| A. Separate classic `project`-only token, used only inside `board.py` (chosen) | The shell token stays narrow; works for a user-owned project | A second token to rotate; `project` scope is account-wide (accepted) |
| B. Add `project` scope to the shell token, or use a classic `repo` token | One token | Widens everything Claude can do (C13) |
| C. Fine-grained token with Projects write | Narrowest | No user-level Projects permission is listed (F31) |

### R. Phase 0 verify items

| Item | Closed by |
|---|---|
| V10 ignores comments | D15 (1a) |
| `check_repo.py` bypasses (flow-style `uses:`, `write-all`, `*.yaml`) | H1, H2 (1b) |
| Intake agent unrestricted Bash and heredoc temp file | D14 (1a) |
| Deny-list glob gaps | S2 guard plus S7 (1c) |
| Hook exclude too wide, console format, `types-PyYAML` lock | H7 (1b) |
| `--json` on unreadable file; `plugin.json` author | D16, D17 (1a) |
| `compat.gitops` dead data | M9 (1a) |
| Concurrency cancels `main` | H8 (1b) |
| `is_prod` by name | D8 (1a) |
| code-simplifier trims (about 90 lines) | Not scheduled; allowed only in files a sub-PR already touches |

### X. Out of Phase 1

`runtime-*` modules and the M10 alarms; adapters and conformance; `reusable-release.yml` jobs; real deploy and apply
profiles; promotion (T6); ship-it-serverless migration (B3 step 5, state moves); a KMS CMK for ECR; the copier
template; `org-baseline`; the `aws-ops` agent (A16); ECS and other families; DP17; DP18; any bootstrap in the lab
accounts; English for Devs (OD5); the Backlog skills of S4.

WA findings not closed in Phase 1, each accepted until its phase:

| WA | What waits | Closes in |
|---|---|---|
| WA1 | Alarms built from the M10 contract | Phase 2 (runtime module) |
| WA8 | Attestation verify and CRITICAL-finding gate at promote (scan on push is in T5) | Phase 2 |
| WA13 | `database.backup` and the backup warning; `dr.region` | Phase 2 |
| WA15 | Timed dev rebuild drill per minor | Phase 2 |
| WA16 | Rule that refuses a throttle above the recorded quota (quota recorded at checkpoint 5) | Phase 2 |
| WA18 | `scale_to_zero` with a tight p95 warning; load test pass mark | Phase 2 |
| WA19 | `arch` reaching the build job | Phase 2 |
| WA24 | Log groups using `log_retention_days` | Phase 2 |
| WA26 | Proxy KPI per 1,000 requests | `aws-ops` (A16) |

## Alternatives considered

| Alternative | Why not |
|---|---|
| Keep one SHA for everything (O3 as written) | Every release, even an intake fix, needs a re-apply per account (DP3) |
| Trust a tag pattern | Mutable; any new tag is trusted (ADR 0001 O3) |
| Dispatch inputs may override strategy, steps or bake | Two sources of release behavior (OD2) |
| Account ID in a GitHub var | Printed unmasked in public step logs |
| Pin the marketplace by SHA | Not supported (F21) |
| Phase 1 checkpoint in the serverless accounts with another prefix | One OIDC provider per account (F25), plus a duplicate trail and budget; mixes the lab with the platform |
| Skip any AWS proof until Phase 2 | F3 and DP4 would first be tested on the real consumer |
| Union egress hosts across runtimes in one job | Widens every credentialed job (A9) |
| Check only `workflow_sha` remotely | An impostor SHA could sit in `trusted_workflow_shas` unchecked (C1, F32) |
| Private canary repo | No required reviewers on Free, Pro or Team (F30) |
| Promotion policy in Phase 1 | No user, and a missing principal fails (T6) |

## Consequences

- One platform version line remains. Trust moves only with `workflow_sha`, at most once per minor (L7), and any
  rule-data change in a minor moves it (accepted).
- The deploy role exists but is unusable until Phase 2 (by design, enforced by L3 (c)).
- `v0.2.0` breaks `v0.1.0` manifests (`tier`, `owner`, `budget`, prod rules V22 to V24). Accepted, because no
  consumer exists.
- The marketplace pin relies on the tag ruleset plus the L3 `--remote` check (accepted).
- The environment gate (required reviewer = owner, self-review allowed, `main` only) protects against a compromised
  token or a Claude session starting an apply. It does not protect against the owner (accepted, solo owner).
- A same-repo PR author can run code as the nonprod plan role and read that env's state (accepted, O14, T4).
- The canary is two Sandbox-OU accounts and one public repo. Cost: trail and state buckets, budgets and the anomaly
  monitor (near zero, S); GuardDuty only if turned on.
- ship-it-safely keeps its frozen guard copy (T8); drift is accepted.

### Owner checkpoint (Phase 1)

Run these by hand, in this order. Step 0 comes before the build; steps 1 to 11 come after it.

0. **Before build** (after this ADR is accepted).
   - Git PAT (fine-grained): Contents, Pull requests and Issues read/write; Metadata and Actions read; Administration
     read for A12 (C), on sis-platform and the canary repo. No Actions write, Administration write, Environments write
     or `project` scope.
   - Board token: create a classic token with only the `project` scope and store it in the Keychain as
     `sis-board-token` (C, F31).
   - Board:
     ```
     gh project create --owner @me --title "sis delivery"
     gh project field-create <n> --owner @me --name Phase --data-type TEXT
     gh project field-create <n> --owner @me --name Kind --data-type SINGLE_SELECT --single-select-options "phase,checkpoint,platform-bump,bug"
     ```
     Set the B4 Status options in the UI (C). Send the project number; the orchestrator opens the `project.env` PR.
1. Merge the sub-PRs in the order of the Build briefs.
2. Release. Run `python3 scripts/release/check_release.py --tag v0.2.0 --sha <merge sha of 1f-2>` and keep its
   output. Then `gh release create v0.2.0 --target <merge sha of 1f-2> --title v0.2.0 --generate-notes`. Confirm that
   the tag ruleset blocks updates.
3. Canary repo. Create the **public** repo `sis-platform-canary` with environments `dev` and `prod`, each with
   required reviewer = you, self-review allowed, deployment branch `main` only (F30). Merge the PR Claude opens there,
   which copies `examples/consumer/` with `platform.lock` filled in.
4. 4a claims smoke, before any account exists (O12). Run
   `gh workflow run oidc-smoke.yml -R <owner>/sis-platform-canary --ref main` and approve the `dev` deployment. Send
   the printed `job_workflow_ref` and the pass or fail line for `AWS_ACCOUNT_ID` (expected: fail, no secret yet;
   this run proves the claim format only). If the value does not end in `@<workflow_sha>`, Claude prepares a patch
   release and steps 2 to 4 repeat.
5. Accounts. Create `<canary>-dev` and `<canary>-prod` under OU `Sandbox`. In each: root MFA on and no root access
   keys (`aws iam get-account-summary`, expect `AccountMFAEnabled` 1 and `AccountAccessKeysPresent` 0; C if root
   access is centrally managed); record the Lambda concurrent executions quota from Service Quotas (WA16, C). Add the
   environment secret `AWS_ACCOUNT_ID` to `dev` and `prod`, and repo secrets `AWS_ACCOUNT_ID_DEV` and
   `AWS_ACCOUNT_ID_PROD`. Rerun step 4 and confirm the `AWS_ACCOUNT_ID` line passes; if it fails, Claude switches the
   apply callers to the O13 fallback.
6. Bootstrap per account. With Identity Center admin credentials, from the canary repo:
   ```
   python3 <sis-platform@release_sha>/scripts/platform/check_lock.py --remote .
   python3 <sis-platform@release_sha>/intake/sis_intake/validate.py platform.yaml --emit tfvars --env dev > "$TMPDIR/platform-dev.tfvars.json"
   terraform -chdir=infra/bootstrap init
   terraform -chdir=infra/bootstrap apply -var-file=accounts/dev.tfvars -var-file="$TMPDIR/platform-dev.tfvars.json"
   ```
   Then remove `backend_override.tf` and run
   `terraform -chdir=infra/bootstrap init -migrate-state -backend-config=accounts/dev.backend.hcl` (gitignored, T3).
   Confirm the SNS email subscription. Check `aws cloudtrail get-trail-status --name <trail>` shows logging and
   `aws accessanalyzer list-analyzers` shows one analyzer. Repeat for prod.
7. Negative test (O12). Run `gh workflow run oidc-negative.yml -R <owner>/sis-platform-canary --ref main -f env=dev`
   and approve the `dev` deployment. Expect AccessDenied for both the apply and the deploy role.
8. Positive proof, the only one (O12). Open a canary PR that touches `infra/envs/dev` (one `terraform_data`); the
   plan comment appears. Merge it and approve the dev apply. Then run
   `gh workflow run terraform.yml -R <owner>/sis-platform-canary -f env=prod` and approve the prod apply.
9. A7, in each account and in both regions:
   ```
   for r in ap-southeast-1 us-east-1; do aws cloudtrail lookup-events --region "$r" --start-time <iso> --query 'Events[].CloudTrailEvent' --output json | jq -r '.[] | fromjson | select((.errorCode // "") | test("AccessDenied|Unauthorized")) | [.eventName, .errorCode] | @tsv'; done
   ```
   Paste only the `eventName` and `errorCode` columns. The only hits should be the step 7 negatives.
10. A12. Run `scripts/github/check-settings.sh <owner>/sis-platform-canary` and
    `scripts/github/check-settings.sh trungleviet-agilityio/sis-platform`.
11. At least 24 hours after the first tagged resource, in the management (payer) account:
    `aws ce update-cost-allocation-tags-status --cost-allocation-tags-status TagKey=Project,Status=Active TagKey=Env,Status=Active TagKey=Owner,Status=Active` (C).

Read `docs/runbooks/oidc-trust-broken.md` and `docs/runbooks/leaked-token-or-bad-commit.md` once before step 6
(WA9).

These stay (C) until the checkpoint:

| Item | Confirmed at |
|---|---|
| F3/F19: `job_workflow_ref` value for a SHA call, and `job_workflow_sha = job.workflow_sha` | Step 4 |
| F29: environment secret resolves for a caller in another owner | Step 5 |
| AWS accepts the O9 value (positive) and refuses the smoke file (negative) | Steps 7 and 8 |
| Fork PRs get no OIDC token in the public canary | Step 8 (check the fork PR setting) |
| F26/F31: classic `project` scope is enough for `gh project` writes; editing Status options | Step 0, then the 1d done check |
| Administration read is enough for rulesets in A12 | Step 10 |
| Root MFA check when root access is centrally managed; the Lambda quota value | Step 5 |
| Plan role read list is complete (missing reads) | Step 9 |
| Cost allocation tag activation | Step 11 |

## Well-Architected review

| Pillar | Best practices | How the design meets it | Gap and phase that closes it |
|---|---|---|---|
| Operational excellence | OPS02-BP01, OPS04-BP01, OPS05-BP01, OPS05-BP04, OPS06-BP04, OPS07-BP02, OPS07-BP03, OPS08-BP04 | One resolved plan (M6) with an observability contract (M10); versioned contracts (K, `format_version`); P9 check on every PR and weekly; `owner` and `tier` tags; board with exact checkpoint commands and a readiness checklist (B14); credentialed jobs never cancel (H10) | Alarms built from M10: Phase 2. Per-runtime readiness review: Phase 2 |
| Security | SEC01-BP01, SEC01-BP02, SEC01-BP06, SEC02-BP02, SEC03-BP02, SEC03-BP07, SEC04-BP01, SEC04-BP02, SEC07-BP01, SEC10-BP02, SEC11-BP06, SEC11-BP07 | Trust by exact `workflow_sha`, N and N-1 only, every trusted SHA proven on `main` (L3); DP4 self-checkout with fail-closed sparse closure; plan role denies secret reads and writes; permissions boundary and escalation lint (T11); trail with validation and Access Analyzer (T7); root checks and break-glass runbooks; `data_class` required for prod (V22); environment gate against token or Claude misuse | Nonprod plan role runs PR code (accepted, O14). GuardDuty off by default (accepted, owner flag). SCPs, Identity Center, organization trail and delegated GuardDuty: `org-baseline`. Attestation gate (SEC11-BP02): Phase 2. KMS CMK: later phase |
| Reliability | REL01-BP01, REL08-BP04, REL08-BP05, REL09-BP01, REL13-BP01 | Versioned state with lockfile and noncurrent lifecycle; `prevent_destroy` on the OIDC provider; immutable ECR whose lifecycle never touches tagged rollback targets in Phase 1; N-1 trust allows platform rollback; resumable adapter states (K5); RTO and RPO required for prod (V23); quota recorded at bootstrap | `live`/`prev` protection and promotion: Phase 2. DR drill (REL13-BP05): Phase 2. DR beyond backup-restore: later phase |
| Performance efficiency | PERF05-BP01, PERF02-BP01 | `peak_rps` and `p95_ms` captured and required for prod (V24); per-family jobs; stdlib validator | No performance workload in Phase 1; PERF05 load test and CI timing baseline close in Phase 2 |
| Cost optimization | COST01-BP06, COST02-BP05, COST03-BP02, COST03-BP03, COST04 | Required budget per account with forecast alerts and an anomaly monitor; cost allocation tags; ECR and state lifecycles; GuardDuty opt-in; canary is two near-empty accounts | Per-project cost report: `org-baseline`. Fixed-cost sum rule: with the first runtime (Phase 2) |
| Sustainability | SUS01-BP01, SUS02-BP03, SUS04-BP03, SUS06-BP01 | Lifecycle policies on state, trail and ECR; a re-apply only when `workflow_sha` moves, at most once per minor; no idle compute in Phase 1; region allowlist (V25) | One region, `ap-southeast-1`, chosen for latency to users and cost: accepted. Log retention applied to log groups: Phase 2 |

## Open questions

None blocking. Refinements taken by default that the owner can reverse before acceptance: OD2a (secret, not var);
L1 (two extra lock fields); L7 (patch never moves trust); the public canary repo; the classic `project`-only board
token (B16).

## Sources

- GitHub contexts, `job.*` properties and the context availability table: https://docs.github.com/en/actions/reference/workflows-and-actions/contexts (V)
- Reusable workflows reference (caller `github` context, permissions downgrade, ref forms): https://docs.github.com/en/actions/reference/workflows-and-actions/reusable-workflows (V)
- Reuse workflows how-to (environment secrets in a reusable workflow, passing secrets by name, `inherit`): https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows (V, F29)
- Deployments and environments (plan availability, required reviewers, prevent self-reviews): https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments (V, F30)
- Fine-grained PAT permissions: https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens (V, F31)
- GitHub OIDC claims: https://docs.github.com/en/actions/reference/security/oidc (V)
- Impostor commits: https://docs.zizmor.sh/audits/#impostor-commit (S, F32)
- `actions/checkout` sparse checkout: https://github.com/actions/checkout (S, F33)
- AWS IAM condition keys for GitHub OIDC: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_iam-condition-keys.html (V, ADR 0001 F1)
- IAM OIDC providers: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html (S for F25)
- ECR tag mutability: https://docs.aws.amazon.com/AmazonECR/latest/userguide/image-tag-mutability.html (S, F34)
- Pricing claims (CloudTrail first management copy, Access Analyzer external access, Cost Anomaly Detection, GuardDuty trial): https://aws.amazon.com/cloudtrail/pricing/, https://aws.amazon.com/iam/access-analyzer/pricing/, https://aws.amazon.com/aws-cost-management/aws-cost-anomaly-detection/pricing/, https://aws.amazon.com/guardduty/pricing/ (S, confirm at build)
- Claude Code marketplace reference: https://code.claude.com/docs/en/plugins/marketplace-reference.md and https://code.claude.com/docs/en/plugin-marketplaces (V)
- Claude Code skills frontmatter: https://code.claude.com/docs/en/skills (V)
- Terraform test mocking: https://developer.hashicorp.com/terraform/language/tests/mocking (V)
- `gh project item-edit`: https://cli.github.com/manual/gh_project_item-edit (V)
- Well-Architected: https://docs.aws.amazon.com/wellarchitected/latest/framework/sec_securely_operate_automate_security_controls.html (V, related BPs); SUS04-BP03 via https://aws.amazon.com/blogs/mt/assess-audit-and-evaluate-aws-resources-against-aws-sustainability-best-practices/ (S); pillars: https://docs.aws.amazon.com/wellarchitected/latest/framework/the-pillars-of-the-framework.html; WA1 to WA26 IDs as read in the note of 2026-11-04 (V there)
- super-board (MIT), credited for guard rules, board flow and the review rubric: https://github.com/EricTechPro/super-board (S)
- Reference code (read, credited in headers): ship-it-safely `infra/terraform/bootstrap/*` (including `iam_ecs_boundary.tf`), `.github/workflows/{reusable-terraform-plan,terraform-iac,oidc-smoke-test,repo-guard}.yml`, `scripts/{aws,tf,guard}/*`, ADR 0002, 0003, 0004, 0007, 0008, 0011; ship-it-serverless ADR 0012, 0013, `plugins/sis-team/**` at eb212c9, `infra/terraform/bootstrap/{ecr,iam_deploy}.tf`
- Versions and action SHAs: pin at build time

## Build briefs

Independent sub-PRs branch from the ADR docs branch and build in parallel worktrees. A dependent sub-PR branches
from the merge of its dependencies (or rebases onto them before review). Shared done checks for every sub-PR:
`make check` green from a clean clone; no file outside the owned paths; the last commit is not WIP; a report of at
most 60 lines.

| Wave | Sub-PRs | Starts after |
|---|---|---|
| 1 | 1a, 1b, 1c, 1e, 1g, 1f-3 | ADR docs branch |
| 2 | 1d | 1c merged and checkpoint step 0 |
| 2 | 1f-1 | 1a and 1b merged |
| 3 | 1f-2 | 1f-1 and 1e merged |

Merge order: 1a, 1b, 1c, 1e, 1g, 1f-3, 1d, 1f-1, 1f-2.

### 1a `phase-1a-intake-contracts` (backend-dev, `intake/**`)

| Item | Content |
|---|---|
| Spec | D1 to D21, V19 to V25, M6 to M10 (intake side), L6 |
| Tests first | One pass and one fail per new rule; `invalid/*` for V19, V20 (three files), V21 to V25 and the D18 schema files; `--json` golden test of the M6 keys (including `observability`, `data_class`, `owner`) and `format_version`; `--emit tfvars`; `--context deploy` exit codes; stdin `-`; the compat/schema/defaults key equality test; registry 1:1; `wa_refs` pattern |
| Done | 3.9 and 3.13 green; ruff and mypy strict clean; README rule table regenerated; `sis_intake.__version__ = 0.2.0` |
| Note | devops-engineer writes `closure.txt` in 1f-1 and covers every runtime path under `intake/`; report any new runtime path |
| Out | Any consumer of M6 outside `intake/` |

### 1b `phase-1b-guard` (devops-engineer)

| Item | Content |
|---|---|
| Spec | H1 to H8, H10, R rows for scripts and CI |
| Tests first | A selftest fixture per rule asserting the message: flow-style unpinned `uses:`, missing version comment, `write-all`, `.yaml` file, `id-token` on a non-assuming job, harden-runner not first, `block` missing, wildcard host, sis-platform checkout without `job.workflow_sha` or `sparse-checkout`, uncovered `.platform/` path, consumer dispatch input other than `env`, `sha` or `digest`, credentialed job with `cancel-in-progress: true` |
| Done | actionlint and zizmor clean; `ci.yml` concurrency fixed |

### 1c `phase-1c-sis-team-plugin` (devops-engineer, `plugins/**`, `.claude-plugin/**`)

| Item | Content |
|---|---|
| Spec | S1 to S6, S8, L4 (entry) |
| Tests first | `test_guard.py` cases for S2 (including the B16 token rules) plus all inherited cases; marketplace JSON test (two relative entries); skill frontmatter test (side-effect skills have `disable-model-invocation: true`) |
| Done | The PR body has the `git diff --no-index` of commit 1; the guard runs under 3.9; no "ship-it-safely lab" text left; credits in file headers |
| Orchestrator | CLAUDE.md agent table (S8) |

### 1d `phase-1d-board` (devops-engineer, `plugins/sis-team/**`; orchestrator: `project.env`, `.claude/settings.json`)

| Item | Content |
|---|---|
| Spec | B9 to B16, S5, S7 (settings after `v0.2.0`) |
| Tests first | `test_board.py` with a stub `gh` on PATH: refuses another project, column or verb; never calls `gh api`; the dry run prints the exact argv; the token reaches only the `gh project` subprocess environment; the Needs-you template renders without 12-digit runs |
| Done | Lifecycle steps in the plan, run and close skills; settings allow and deny rules added; after a dry run, the orchestrator runs one real `board.py add` and one `move` on the Phase 1 card and pastes the result |

### 1e `phase-1e-account-bootstrap` (devops-engineer, `modules/**`, `mise.toml` Terraform lines, `Makefile` `tf-check`, `scripts/tf/**`; orchestrator: `.claude/rules/terraform.md`)

| Item | Content |
|---|---|
| Spec | T1 to T11, O9 (trust values), O14, H9 |
| Tests first | tftest files of T9, including: trust holds exactly 1 or 2 SHAs, rejects 3 or a non-hex; refs built per role file; deploy trusts `reusable-release.yml` only; prod plan trust has no `pull_request` sub; plan role denies; structural precondition fails on `*` actions, `NotAction` and `NotResource` in string and list forms; profile-name precondition; `create_oidc_provider = false` uses lookup; ECR lifecycle rules; trail, analyzer and GuardDuty flag defaults; `policy.py` fixtures for each T11 failure, including escalation without the boundary condition |
| Done | `make tf-check` green offline; README with terraform-docs; no `provider` or `backend` in the module; `PROFILES.md` with the boundary interface |
| Depends | Builds against the M6 spec in this ADR; rebases on 1a before review |

### 1g `phase-1g-contract-docs` (devops-engineer, `adapters/**`; orchestrator: `docs/runbooks/**`)

| Item | Content |
|---|---|
| Spec | K1 to K8; runbooks `oidc-trust-broken.md`, `leaked-token-or-bad-commit.md`, `restore-from-zero.md` (WA9, WA14) |
| Tests first | Both schemas pass the Z4 metaschema check; a sample result line validates |
| Done | No adapter code; runbooks hold no account IDs |

### 1f-1 `phase-1f1-lock-closure` (devops-engineer, `scripts/platform/**`, `scripts/release/**`, `examples/consumer/**` except workflows)

| Item | Content |
|---|---|
| Spec | L1 to L5, L7, `closure.txt` (covers backend-dev's intake paths) |
| Tests first | `check_lock.py` fixtures for each L3 failure, including each trusted-SHA check (not on `main`, not a released `workflow_sha`, contains `reusable-release.yml`); the closure computation on a fixture git repo with `:(glob)`, a rename and a sourced file; `check_release.py` fails a patch that moves `workflow_sha`; `examples/consumer` passes offline L3 |

### 1f-2 `phase-1f2-workflows-oidc` (devops-engineer, `.github/**`, `examples/consumer/.github/**`)

| Item | Content |
|---|---|
| Spec | W1 to W7, O10 to O13, the canary callers `oidc-smoke.yml`, `oidc-negative.yml`, `terraform.yml`, `platform-check.yml` (weekly schedule) |
| Tests first | The reusable workflows pass H1 to H6 and H10; `examples/consumer` passes the `consumer` guard profile |
| Done | actionlint and zizmor clean; harden-runner egress lists recorded in the PR; no AWS call anywhere |

### 1f-3 `phase-1f3-settings-check` (devops-engineer, `scripts/github/**`)

| Item | Content |
|---|---|
| Spec | A12 `scripts/github/check-settings.sh` (read-only `gh api` GET: visibility, rulesets, required checks, environments, reviewers, branch policy, secret and variable names against the O13 allowlist, Actions SHA pinning) |
| Tests first | Self-test with recorded JSON |
| Done | bash 3.2 compatible; no write verb |

## Amendment A (2026-11-04): decisions from the wave 1 build and verify

- Status: accepted (owner, 2026-11-04)
- Source: peer reviews of 1a, 1b, 1c, 1e, 1g and 1f-3, and the wave 1 verify (e2e, reviewer, security-reviewer,
  code-simplifier) on the integration branch.

| # | Decision | Amends | Pillars |
|---|---|---|---|
| AA1 | One env name rule everywhere: `^[a-z][a-z0-9]{1,7}$` (2 to 8 chars, no hyphen). It holds for intake `envs` keys, `var.env` in `account-bootstrap`, the adapter result `env` and `release_id`, and the repo secret `AWS_ACCOUNT_ID_<ENV>` (GitHub secret names cannot hold a hyphen) | M6, K3, O13 | OPS, REL |
| AA2 | The git PAT that Claude's shell uses has no Deployments write, Actions write or Administration write, so it can never approve an environment deployment or change settings. A12 needs Secrets read and Variables read to list names (C at step 10) | B16, checkpoint 0 | SEC |
| AA3 | AWS has no `event_name` condition key (V). The Phase 2 reusable apply and release workflows refuse any event other than `push` and `workflow_dispatch` in their first step; H rules check it | W, O9 | SEC |
| AA4 | `closure.txt` lists exact runtime files for `scripts/tf` (`policy.py`, `check.sh`, `resolved-sources.sh`), not `scripts/tf/**`, so tests and fixtures never move `workflow_sha` | L2, L7 | OPS |
| AA5 | Plan role: AWS managed ReadOnlyAccess plus explicit denies (secrets, SSM decryption, KMS decrypt, S3 outside state, and the non-read or data-plane actions ReadOnlyAccess grants, such as `sqs:Receive*`, `s3express:CreateSession`, DynamoDB item reads, log event reads). No service-wildcard `NotAction` (IAM grammar documents wildcards in action names only) | T4 | SEC |
| AA6 | Escalation rules are enforced twice: by `policy.py` (P06, P07, P09, P10, P11) and by guardrail denies in IAM (role writes without the boundary, boundary deletion, PassRole without `iam:PassedToService`). At checkpoint step 6 the owner also runs `policy.py` on `terraform show -json` of the bootstrap plan before apply | T8, T11, checkpoint 6 | SEC |
| AA7 | CI runs `tf-check` in its own job with terraform, tflint and terraform-docs installed by checksum; `check` needs it | H9 | OPS |
| AA8 | Claude guard: path-scoped writes and `rm -r` allow the git toplevel and Claude's own scratch dir `/tmp/claude-<uid>` (real directory, owned by the user, not group or world writable); shells fed by stdin, here-strings or process substitution are checked or blocked; release tags and `gh release` writes are blocked. Accepted limits of a text guard: interpreters other than shells and python (`perl -e`), commands built from variables, git aliases via `-c`, scripts written then run, `.git/hooks`. Backstops: no AWS credentials in the shell, the `main` ruleset, and AA2 | S2, A14 | SEC |
| AA9 | The intake interviewer agent has no Bash; the intake skill in the orchestrating session runs the validator on the draft (D14 implementation) | D14 | SEC |
| AA10 | Adapter contract additions marked "(1g addition)" in `adapters/CONTRACT.md` are accepted: rollback inputs (`SIS_PREV_DIGEST` is the target that becomes live), `contract_check.py` as the shared cross-field checker for K7, refs as `""` when empty | K | OPS, REL |
| AA11 | A checkout of sis-platform in a non-reusable workflow is not checked by H5; accepted, because roles are only reachable through the pinned reusable workflows | H5 | SEC |
| AA12 | Deferred to the first PR of wave 2: ruff and mypy scope widened to `plugins/**`, `adapters/**` and all of `scripts/**` | H9 | OPS |

Stays (C) until the checkpoint, in addition to the list above: the size of the guardrail managed policies against the
6144-character limit, the `sha_pinning_required` field in the Actions permissions API, Administration read for
rulesets, and the event refusal of AA3 in a live run.

## Amendment B (2026-11-04, proposed): decisions from the wave 2 build and verify

- Status: proposed (owner to accept with the wave 2 PRs)
- Source: peer reviews of 1h and 1f-1, and the wave 2 verify (e2e release simulation, security review).

| # | Decision | Amends | Pillars |
|---|---|---|---|
| AB1 | `intake/sis_intake/__init__.py` holds only a docstring and `__version__` (a test parses it with `ast`) and is excluded from the closure (`:(exclude,glob)`). Without this, L4 (version = tag) moves `workflow_sha` on every release and no patch release is possible under L7 | L2, L4, L7 | OPS |
| AB2 | `scripts/tf/check.sh` is not in the closure: it is a module-development check that runs tests outside the closure. Reusable workflows call `scripts/tf/policy.py` and `scripts/tf/resolved-sources.sh` directly | AA4 | OPS |
| AB3 | `closure.txt` lines are only `:(glob)<path>` or `:(exclude,glob)<path>`; any other pathspec magic is refused. `workflow_sha` requires linear history (squash merges); a history with merge commits is refused | L2 | REL |
| AB4 | `resolved-sources.sh` requires sis-platform module sources to match the lock's `release_sha` exactly, not any 40-hex value | H9, L3 | SEC |
| AB5 | Offline L3 also refuses: a module `source` that is not one plain string literal; local sources through `.terraform` or `.git`, or that resolve outside the repo; symlinked directories or symlinks leaving the repo; duplicate YAML keys; a sis-platform `uses:` path other than `.github/workflows/reusable-*.yml`; `*.tf.json`, `.tofu` and every `action.yml` are scanned | L3 | SEC |
| AB6 | Release prep bumps all three version files (`intake/.claude-plugin/plugin.json`, `plugins/sis-team/.claude-plugin/plugin.json`, `intake/sis_intake/__init__.py`) to the tag; `check_release.py` reads plugin roots from `marketplace.json`. A patch release needs an ancestor previous tag | L4, L7 | OPS |
| AB7 | mypy 2.x no longer type-checks against a Python 3.9 target; 3.9 compatibility is enforced by running every test suite on Python 3.9 (accepted) | Z3 | OPS |
| AB8 | Requirements for 1f-2: no `uses: ./` in reusable workflows (H rule exists); sparse-checkout patterns are derived from `closure.txt`; `plan-summary.sh` and `assert-no-account-id.sh` live in closure paths; PyYAML and tool installs inside workflows are pinned and hash-checked; `check_lock.py --remote` runs as the required W5 check | W, O11 | SEC |

Accepted residual risks: offline L3 trusts the lock values a PR commits (only `--remote`, a required check, proves
they are released); a consumer can vendor platform code through local paths; a third-party wrapper workflow calling
sis-platform at another SHA is invisible to L3 (IAM `job_workflow_ref`, O9, is the enforcement); tag integrity relies
on the immutable tag ruleset.

## Amendment C (2026-11-04, proposed): decisions from the 1f-2 build and verify

- Status: proposed (owner to accept with the 1f-2 PR)
- Source: the 1f-2 build, its peer review, and the wave 3 verify (e2e offline replay of every `run:` step,
  reviewer, security review twice, code-simplifier).

| # | Decision | Amends | Pillars |
|---|---|---|---|
| AC1 | The `consumer` guard profile also allows `schedule`, so the weekly W5 `platform-check.yml` can live in the consumer repo. `workflow_dispatch` inputs stay limited to `env`, `sha`, `digest` | H4, W5 | SEC, OPS |
| AC2 | Sparse-checkout patterns are written literally in every reusable job (`:(glob)X` becomes `/X`, `:(exclude,glob)X` becomes `!/X`), and `scripts/ci/check_sparse.py` fails CI unless each list equals `closure.txt` in order. This is how AB8 "derived from closure.txt" is met: the file cannot be read before the checkout, and literal lists stay visible to the guard (H6) | O11, AB8 | SEC |
| AC3 | `resolve.py` (closure) runs in every job that needs resolved values, because jobs share no disk. It checks the trust (O11), the M6 manifest, the M7 `SIS_PROJECT_PREFIX` in the caller's `project.env`, and that the family is one this workflow has a job for (`SUPPORTED_FAMILIES`, a literal per workflow, kept equal to the `if:` gates by a selftest). An unsupported family fails instead of skipping green | W2, M7 | REL, SEC |
| AC4 | Event and ref allowlists in the first step after harden-runner: plan accepts `pull_request`, `push`, `workflow_dispatch`, `schedule`; apply accepts `push` and `workflow_dispatch` on `refs/heads/main` only, repeated before the credential, and also refuses a run whose `github.sha` is not the current `main` tip (stale re-run); the smoke accepts `workflow_dispatch` on `refs/heads/main`. A `check_repo.py` rule enforces the apply step (the H rule AA3 asked for). All reusable workflows set `defaults.run.shell: bash` (pipefail) | AA3, W4, O12 | SEC, REL |
| AC5 | The stale-apply check uses an anonymous `git ls-remote` over `github.com`, so it needs a public consumer repo (the canary is public, F30). Options: (a) anonymous, public repos only (chosen for Phase 1); (b) authenticate with the job token for private consumers (Phase 2, when the first private consumer appears). A race with a newer `main` push between the check and the apply is accepted: the newer run queues behind `tf-<env>` | W4 | SEC |
| AC6 | Provider supply chain: a closure file `scripts/platform/terraformrc` sets `provider_installation { direct { include = ["registry.terraform.io/hashicorp/*"] } }` through `TF_CLI_CONFIG_FILE`, which disables implied local mirrors. `init -backend=false -lockfile=readonly`, then `resolved-sources.sh`, then `validate` all run before the role is assumed; the backend init after it runs `resolved-sources.sh` again | H9, AB4, O14 | SEC |
| AC7 | Raw `terraform plan` and `apply` output goes to a file under `$RUNNER_TEMP`, not the public log. On failure it is printed with every 12-digit run and every `dddd-dddd-dddd` run replaced by `<account>`. The PR comment and step summary stay the account-free summary (W3). `assert-no-account-id.sh` also catches the dashed form | W3, H7 | SEC |
| AC8 | `scripts/tf/policy.py --allow-no-policy` returns 0 with a note when the plan holds no IAM policy (default exit 2 unchanged for module checks). The workflows call `policy.py` directly. Because a no-policy pass must not hide IAM changes, `policy.py` also lints `aws_iam_role` `inline_policy` (unknown at plan time fails closed, P00), fails any AWS managed policy attached by any attachment type or `managed_policy_arns` (P12, allowlist empty in Phase 1), and under the flag fails any created or updated `aws_iam_*` type it does not read (P13). Phase 2 runtime roles set no `inline_policy` and no `managed_policy_arns`; grants come only from linted documents | T11 | SEC |
| AC9 | State backend over path-style S3 (`use_path_style = true`), so the credentialed jobs need one literal host, `s3.<region>.amazonaws.com`. Options: (a) path style (chosen; H3 allows only the account secret and the region in a host); (b) let H3 accept the M6 prefix and pin the virtual-hosted bucket host. Switch to (b) in a patch if (a) fails with account-regional buckets at step 8 (C) | T3, H3 | SEC, REL |
| AC10 | W5 egress: `reusable-platform-check.yml` has no credentials and runs harden-runner `audit` with `github.com`, `pypi.org` and `files.pythonhosted.org`, because AB8 requires PyYAML installed by hash (`--require-hashes --only-binary --no-deps`) | W5, AB8 | SEC |
| AC11 | `reusable-oidc-smoke.yml` is exempt from the H3 family gate: it calls no AWS service except, in `check: negative`, unsigned STS (`sts.<region>`); the claims job egress is `github.com` only. Input `check` is `claims` (default) or `negative`; any other value fails | H3, O12 | SEC |
| AC12 | Step 7 proves a refused trust only after step 8 has proved the same apply role ARN, because STS also answers AccessDenied for a missing role or another account. The owner re-runs step 7 after step 8. The deploy role has no positive proof in Phase 1 (inert by design, L3 c) | O12 | REL, SEC |
| AC13 | `.github/actionlint.yaml` ignores only the `job.workflow_*` properties (F17) until actionlint knows them | H1 | OPS |
| AC14 | `examples/consumer/infra/envs/{dev,prod}` is a minimal root (empty `backend "s3" {}`, AWS provider pinned, committed `.terraform.lock.hcl`, one `terraform_data`), so the canary callers run from day one. The first push to the canary `main` queues a dev apply; the owner rejects it until step 8 | Checkpoint 3 | OPS |

Accepted residual risks, in addition to Amendment B:

- The W5 check runs the workflow file of the PR it checks (GitHub runs `pull_request` workflows from the merge
  ref), so one PR can repin `uses:` and add the same SHA to `trusted_workflow_shas`. IAM `job_workflow_ref` (O9),
  applied by the owner, is the enforcement. Mitigation for the canary: CODEOWNERS review on `platform.lock` and
  `.github/workflows/**` (C, whether rulesets can require it on this plan).
- A same-repo PR runs code as the nonprod plan role (O14). Besides the S3 host, `github.com:443` is open, so the
  role's reads can leave the runner. Accepted, limited by the T4 denies.
- The prod plan role pins no workflow file, so any workflow on `main` or any job with `environment: prod` in the
  consumer repo can assume it (O14 as written). Accepted, read-only and limited by T4.
- The plan comment renders PR-controlled resource addresses as markdown on the author's own PR. Accepted.

Stays (C) until the checkpoint: GitHub fills `job.workflow_repository`, `job.workflow_file_path` and
`job.workflow_sha` in a cross-repo reusable call (F17, F28); harden-runner `block` lets the OIDC token request
through with only `github.com` listed (record the host seen at step 4a); the `job_workflow_ref` format (O12 4a);
the environment secret resolves cross-owner (F29); path-style S3 with account-regional buckets and the Lambda host
list (step 8); the PyYAML wheel hash on `ubuntu-24.04`.

## Change log

| Date | Change |
|---|---|
| 2026-11-04 | Drafted |
| 2026-11-04 | Revised after challenger review C1 to C27: every trusted SHA checked remotely (L3); both environments gated, public canary (F30); claims smoke before any account (O12); trust moves batched (L7); fail-closed sparse closure (L2, O11); plan role denies and prod plan from `main` (T4, O14); escalation lint and boundary (T11); one full policy linter (T8); promotion deferred (T6); environment secret mechanism documented with a fallback (O13, F29); detective baseline (T7); ECR lifecycle (T5); separate board token (B16) and a before-build checkpoint; parallel sub-PR waves; WA findings added (M10, D18 to D21, H10, B14) or recorded with their phase |
| 2026-11-04 | Amendment A: decisions from the wave 1 build and verify (accepted by the owner) |
| 2026-11-04 | Amendment B (proposed): decisions from the wave 2 build and verify |
| 2026-11-04 | Amendment C (proposed): decisions from the 1f-2 build and verify |
