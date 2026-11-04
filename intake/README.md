# intake

The `platform.yaml` manifest contract for sis-platform: a JSON Schema, a stdlib-only validator, the decision
rules, and the `sis-intake` Claude Code plugin that interviews a user and drafts a manifest. The spec is
`docs/adr/0001-platform-boundary-and-phase-0.md` (sections M, D, Z2 to Z8) as amended by
`docs/adr/0002-phase-1-shared-core.md` (M6 to M10, D8 to D21, V19 to V25). The rule files and the table below are
authoritative over the copies in ADR 0001 (L6).

Runtime code is Python standard library only and runs on Python 3.9 and later. PyYAML is used only by one test,
which skips with a notice when it is missing.

## Layout

| Path | What |
|---|---|
| `schema/platform.schema.json` | JSON Schema 2020-12, `$id: urn:sis-platform:platform:1` |
| `sis_intake/yamlsubset.py` | YAML subset loader (below) |
| `sis_intake/schema.py` | Interpreter for the schema keyword subset (below) |
| `sis_intake/rules.py` | One predicate per rule V01 to V25 (`@rule` registry), plus tier, engine and profile resolution |
| `sis_intake/plan.py` | The resolved plan (`--json`) and the Terraform variable slice (`--emit tfvars`) |
| `sis_intake/validate.py` | The CLI |
| `sis_intake/ruletable.py` | Generates the rule table below from `rules/rules.json` |
| `rules/rules.json` | Rule catalog V01 to V25 (thresholds live in `params`) |
| `rules/compat.json` | Capabilities per runtime (family, strategies, engines, flags, alarms, built flags), deploy role profiles |
| `rules/defaults.json` | Runtime and tier defaults (table D), allowed regions, arm64 default for new apps |
| `rules/questions.json` | Intake question groups Q1 to Q10 |
| `examples/valid/`, `examples/invalid/` | Examples; each invalid file starts with `# expect: <ID>` |
| `.claude-plugin/plugin.json`, `skills/intake/`, `agents/intake-interviewer.md` | The intake plugin |
| `tests/` | `python3 -m unittest discover -s intake/tests -t intake` (run from the repo root) |

## CLI

```
python3 intake/sis_intake/validate.py FILE|- [--json] [--context lint|deploy]
python3 intake/sis_intake/validate.py FILE|- --emit tfvars --env ENV
python3 -m sis_intake.validate FILE|- ...            # from intake/
```

`-` reads the manifest from stdin (the intake agent uses this, so it writes no temp file).

| Exit code | Meaning |
|---|---|
| 0 | Valid. Warnings are printed |
| 1 | One or more errors |
| 2 | Parse error or usage error (unreadable file, wrong arguments) |

Each finding has `id`, `severity` (`error` or `warning`), `path`, `message`, `pillars`, `wa_refs`. Parse and schema
problems use the ids `PARSE` and `SCHEMA`. Without `--json` the validator prints the findings, the resolved release
`engine` and `deploy_role_profile` per env, and the runtime defaults.

`--context lint` (the default) reports V17 (something not built yet) as a warning. `--context deploy` makes it an
error, so a manifest that needs an unbuilt runtime, engine, delivery mode or deploy role profile exits 1.

When the manifest fails the schema, only rule V10 (a scan for 12-digit numbers) runs besides the schema errors. V10
scans the raw text, so a number in a comment is found too.

### Resolved plan (`--json`)

`--json` always prints one JSON document (ADR 0002 M6), also for an unreadable file (a `PARSE` finding, exit 2).
Keys, in order: `format_version` (1), `platform_version`, `schema_version`, `context`, `valid`, `findings`,
`project{name,prefix,owner}`, `runtime{kind,family,arch,front_door}`, `workload{port,health_path,peak_rps,p95_ms}`
and `envs`. When the manifest fails the schema, `project`, `runtime` and `workload` are null and `envs` is empty.

Per env: `tier`, `account` (label), `region`, `prefix` (the project prefix), `delivery`, `promote_from`, `strategy`,
`steps`, `bake_minutes`, `probes`, `rollback`, `engine`, `deploy_role_profile`, `roles{plan,apply,deploy}` (names
`<prefix>-<env>-gha-<verb>`, never ARNs), `budget_monthly_usd` (the project ceiling), `data_class`,
`observability{slo{availability_pct,p95_ms},alarms[],log_retention_days,notify}` and
`built{runtime,engine,delivery,profile}`. Defaults come from `rules/defaults.json`: the `tiers` table (a `prod` tier
env defaults to canary, steps 10 and 100, bake 5, rollback alarm and probes `<health_path>` and `/version`; a
`nonprod` one to all-at-once with manual rollback) and the runtime's `release_strategy` per tier. Alarm names are
`<prefix>-<env>-<alarm>` from the runtime's `alarms` in `rules/compat.json`; `notify` is `<prefix>-<env>-notify`.
Log retention is 14 days nonprod, 90 prod, 365 for `data_class: regulated`.

Adding a key is a minor change. Renaming or removing one bumps `format_version`.

### Terraform variables (`--emit tfvars`)

`--emit tfvars --env ENV` prints `{"platform": {...}}`: the env's plan keys, flat, plus `env`, `format_version`,
`platform_version`, `schema_version`, `project`, `runtime` and `workload`. It prints nothing and exits 1 (or 2) when
the manifest has errors. It cannot be combined with `--json`. CI writes it under `$RUNNER_TEMP`, never into the repo.

### Capability data (`rules/compat.json`)

Per runtime: `family`, `strategies`, `engines`, `auto_engine`, `engine_strategies`, `gradual_needs_alb`, `gitops`,
`fixed_monthly_usd`, `two_versions_live` (the strategies that run two versions at once), `env_flags`, `alarms` and
`built{runtime, engines{}, delivery{}, profiles{}}`. Every `built` flag is false in Phase 1; the phase that builds an
adapter flips its flags. Predicates read this data, never a runtime name or a price.

## YAML subset

The manifest is YAML, but the standard library has no YAML parser, so `sis_intake/yamlsubset.py` reads a small
subset and fails closed with the line number.

Supported:

- Block maps (`key: value`) and block lists (`- item`, and `- key: value` for a list of maps), indented with spaces.
- Plain scalars, single-quoted and double-quoted strings (escapes: `\\`, `\"`, `\n`, `\t`, `\/`).
- `true` and `false`, `null` or `~` or an empty value, and integers.
- Comments (`# ...` at the start of a line or after a space).
- Flow lists of scalars (`[10, 100]`) and flow maps of scalars (`{a: 1, b: x}`) on one line.

Rejected, with the line number:

- Anchors (`&x`), aliases (`*x`), tags (`!x`), multiple documents (`---`), block scalars (`|`, `>`), multi-line
  scalars, nested flow collections, tab indentation, duplicate keys, a list at the same indent as its key.
- Plain scalars YAML 1.1 would read as something other than string, int, bool or null: floats, dates, `yes`/`no`/
  `on`/`off`, `0x` and octal forms. Quote them to keep a string.

The intake writes only what the loader reads. A test compares the loader with `yaml.safe_load` on every valid example
(skipped when PyYAML is not installed; CI always runs it).

## Schema keyword subset

`sis_intake/schema.py` interprets: `type`, `enum`, `const`, `required`, `properties`, `additionalProperties`,
`minProperties`, `propertyNames`, `items`, `pattern`, `minimum`, `maximum`, `minItems`, and `$ref` to a local `#/$defs/<name>`. The annotation
keywords `$schema`, `$id`, `$defs`, `title` and `description` are accepted. A test fails when the schema uses any
other keyword. Every object in the schema sets `additionalProperties: false`.

A manifest names accounts by label only (`account: dev`). The label maps to an account ID in the project repo's
GitHub environment variables; the manifest never holds an ID (rule V10).

## Rules

Generated from `rules/rules.json`; do not edit by hand. Regenerate with
`python3 -m sis_intake.ruletable --write` (from `intake/`). A test fails when this table is out of date.

<!-- rules:begin (generated by sis_intake/ruletable.py, do not edit) -->
| ID | Rule | Sev | Pillars | WA ref |
|---|---|---|---|---|
| V01 | `canary` or `linear` requires `rollback: alarm` | E | REL, OPS | OPS06-BP04, REL08-BP05 |
| V02 | `canary`/`linear` need `steps` rising and ending at 100, and `bake_minutes` >= 1 | E | REL | OPS06-BP03 |
| V03 | `delivery: gitops` only for a runtime whose `gitops` capability is true (`eks-workload`) | E | OPS | OPS06-BP03 |
| V04 | (runtime, strategy, engine) must be in the compatibility matrix | E | OPS, REL | REL08-BP05 |
| V05 | canary, linear or blue-green on a runtime that needs an ALB for gradual release (`ecs-fargate`, `ec2-asg`) need `front_door: alb` | E | REL | OPS06-BP03 |
| V06 | ALB needed and `budget.monthly_usd` < 40 | W | COST | COST02-BP05 |
| V07 | `blue-green` doubles capacity during a deploy | W | COST, SUS | SUS02-BP01 |
| V08 | A runtime limit from compat `limits` is exceeded (Lambda: `max_duration_seconds` > 900, `max_payload_mb` > 6) or `needs` contains something the runtime cannot provide (Lambda: gpu, os, licence, websockets) | E | PERF | PERF01-BP01, PERF02-BP01 |
| V09 | `front_door: http-api` with `max_duration_seconds` > 29 | E | PERF, REL | PERF02-BP02 |
| V10 | A 12-digit number anywhere in the manifest text, including comments and placeholders | E | SEC | SEC01-BP06 |
| V11 | A `tier: prod` env needs `promote_from` (one artifact promoted by digest) | E | SEC, REL | SEC11-BP06, REL08-BP04 |
| V12 | `database.kind != none` and a strategy that runs two versions at once (per the runtime's `two_versions_live`) needs `database.schema_change: expand-contract` | E | REL | REL08-BP02 |
| V13 | `dr.rto_minutes` < 60 with `backup-restore`, or < 10 without warm-standby or multi-site | W | REL | REL13-BP01, REL13-BP02 |
| V14 | `warm-standby` or `multi-site` with `budget.monthly_usd` < 100 | W | COST, REL | COST02-BP05 |
| V15 | A runtime with a fixed monthly cost (`eks-workload` control plane) and `budget.monthly_usd` < 100 | W | COST | COST05-BP03 |
| V16 | `scale_to_zero` or `fargate_spot` on a `tier: prod` env | W | REL | REL10-BP01 |
| V17 | Runtime, engine, delivery or deploy role profile not built yet, or `ci.provider: codepipeline`. A warning under `--context lint`, an error under `--context deploy` | W | OPS | OPS07-BP02 |
| V18 | A `tier: prod` env with `rollback: manual` and a strategy other than all-at-once | W | OPS | OPS06-BP01 |
| V19 | `canary` or `linear` needs `release.probes` with at least one path other than `workload.health_path` | E | REL, OPS | OPS06-BP04, OPS04-BP02 |
| V20 | `promote_from` names an existing, different env; the promote graph is acyclic; account labels are distinct across envs | E | REL, SEC | REL08-BP04, SEC01-BP01 |
| V21 | An env flag (`scale_to_zero`, `fargate_spot`) must be in the runtime's `env_flags` | E | OPS | OPS06-BP03 |
| V22 | A `tier: prod` env needs `compliance.data_class`; `data_class: regulated` needs `kms_cmk: true` | E | SEC | SEC07-BP01, SEC08-BP01 |
| V23 | A `tier: prod` env needs `dr.rto_minutes` and `dr.rpo_minutes` | E | REL | REL13-BP01 |
| V24 | A `tier: prod` env needs `workload.peak_rps` and `workload.p95_ms` | E | PERF | PERF05-BP01 |
| V25 | `envs.<e>.region` must be in `defaults.json` `allowed_regions` (Phase 1: `ap-southeast-1`) | E | SUS, SEC | SUS01-BP01 |
<!-- rules:end -->

## Intake plugin

`sis-intake` (version 0.2.0) lives at the plugin root `intake/` and is listed in the repo marketplace. Its skill
`intake` runs the interview one question at a time from `rules/questions.json` and returns three drafts as text:
`platform.yaml`, a first ADR with a Well-Architected review table, and a pipeline proposal. The orchestrating session
in the project repo writes them.

Validation (ADR 0002 D14): the `intake-interviewer` agent has the tools Read, Grep and Glob only, no Bash, so it
cannot run anything. It returns the draft manifest as text. The skill, run in the orchestrating session, pipes the
draft to `python3 "${CLAUDE_PLUGIN_ROOT}/sis_intake/validate.py" -` on stdin (no temp file) and sends the findings
back to the interviewer until there are 0 errors. The agent never writes into the project repo.

## Limits

- Env names match `^[a-z][a-z0-9]{1,7}$` (2 to 8 characters, no hyphen). They feed IAM role names, alarm and topic
  names, the Terraform module's env input (2 to 8 characters) and the GitHub secret `AWS_ACCOUNT_ID_<ENV>`, which
  cannot contain a hyphen.
- Input is capped at 1 MB (file or stdin). Over it, the validator reports a `PARSE` finding and exits 2 (JSON with
  `--json`).
- Plain text output shows the resolved plan and runtime defaults only for a manifest with no errors.

## Output hygiene

No output carries an account-ID-like run (12 digits, or the hyphenated 4-4-4 form; `1234-5678-9012` from the AWS
docs is allowed). Finding messages, paths and plan values are redacted, and `platform_version` is null unless it
matches `vX.Y.Z`. V10 still reports the number, by line. Digit runs inside a longer hex string (a commit SHA) are not
reported.
