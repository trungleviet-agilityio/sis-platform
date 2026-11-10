# Adapter contract v1

Specification only (ADR 0002, K1 to K8). Phase 1 ships this document and two schemas; no adapter exists yet.
Phase 2 builds one adapter per runtime kind against it. A change to `contract_version` is a platform major bump
(K8, P8).

| File | Purpose |
|---|---|
| `adapter.schema.json` | Shape of `adapters/<kind>/adapter.json` (K6) |
| `result.schema.json` | Shape of the one JSON line every verb prints (K3) |
| `contract_check.py` | Importable cross-field checks (stdlib), used by the tests and the Phase 2 conformance suite |
| `tests/test_schemas.py` | Offline tests of both schemas and the cross-field rules below |

Both schemas use only the keyword subset that `intake/sis_intake/schema.py` interprets, so one stdlib
interpreter validates the manifest, the declaration and the result line.

## Verbs (K1)

Each verb is an executable `adapters/<kind>/<verb>`. Rollback is "deploy an earlier digest" (P4).

| Verb | Does |
|---|---|
| `deploy` | Publish the digest, verify it, shift traffic by the plan's strategy and steps, bake, finish or roll back |
| `verify` | Run the plan's probes against the candidate or the live release |
| `rollback` | Deploy `SIS_PREV_DIGEST` to live, using the same path as `deploy` |
| `status` | Report the state of the release without changing anything |

## Inputs (K2)

Inputs are environment variables only. No flags, no stdin.

| Variable | Meaning |
|---|---|
| `SIS_CONTRACT_VERSION` | `1`. The adapter refuses (exit 2) any other value (1g addition) |
| `SIS_PLAN` | Path to the resolved plan JSON (M6) |
| `SIS_ENV` | Environment name; a key of `envs` in the plan |
| `SIS_DIGEST` | `sha256:` plus 64 hex, the image or artifact digest. In `rollback` it is the digest being rolled back from |
| `SIS_SHA` | 40-hex source commit of the digest |
| `SIS_RELEASE_ID` | `<env>-<first 12 hex of the digest>` (K5) |
| `SIS_PREV_DIGEST` | Rollback only: the target digest that becomes live |

In `rollback`, `SIS_PREV_DIGEST` is the target and `SIS_DIGEST` is the digest being rolled back from.
`SIS_RELEASE_ID` stays that of `SIS_DIGEST`. The result line describes the target: its `digest` is
`SIS_PREV_DIGEST` and its `release_id` is derived from it (K5). `SIS_SHA` belongs to `SIS_DIGEST`, so a rollback
line carries the commit of the target as the adapter knows it and is not compared with `SIS_SHA` (1g addition).

The adapter reads strategy, steps, bake, probes, rollback, prefix and the M10 alarm names from the plan only. It
reads no other source of release behavior (no extra variables, no repository files). The old `PREFIX` and
`STRATEGY` variables of A2 are folded into the plan.

## Output (K3)

Exactly one JSON line on stdout, validated by `result.schema.json`. Logs go to stderr. Fields:

| Field | Meaning |
|---|---|
| `contract_version` | `1` |
| `verb` | The verb that ran |
| `env`, `release_id`, `digest`, `sha` | Echo of the inputs |
| `live_ref` | Runtime-specific reference of what serves traffic (Lambda version, task definition revision, ASG revision, rollout revision). Empty string if none |
| `candidate_ref` | Same, for the release being rolled out. Empty string if none |
| `traffic.candidate_percent` | Integer 0 to 100 sent to the candidate. `env` is 2 to 8 lowercase letters or digits starting with a letter, no hyphen, the same shape as `project.prefix` in the manifest and the module; `release_id` follows (1g addition) |
| `state` | See below |
| `endpoint` | URL of the front door, or empty string |
| `message` | One human sentence, no secrets, no account IDs |

`*_ref` fields are opaque strings to the platform. They replace A2's `version` and `live_version`.

## State and exit codes (K4)

States: `publishing`, `verifying`, `shifting`, `baking`, `succeeded`, `failed`, `rolled_back`.

| Exit | Meaning | States allowed on the line |
|---|---|---|
| 0 | succeeded | `succeeded` |
| 1 | failed | `failed`, `rolled_back` |
| 2 | refused (precondition or policy, nothing changed) | `failed` |
| 3 | in progress | `publishing`, `verifying`, `shifting`, `baking` |

Rules a JSON Schema in the Z4 subset cannot state, checked by `contract_check.py`, the tests and the conformance suite:

1. `release_id` equals `<env>-<first 12 hex of the digest>` (K5).
2. The state fits the exit code, per the table above.
3. `succeeded` carries `candidate_percent` 100 and `rolled_back` carries 0. Every other state takes any value
   from 0 to 100, so a failed partial shift can report the share it left on the candidate (1g addition).
4. `verb`, `env` and `digest` echo the inputs (in `rollback`, `digest` is `SIS_PREV_DIGEST`); `sha` echoes
   `SIS_SHA` except in `rollback`.
5. Every failure path still prints a result line (with `state` `failed`) before it exits non-zero, so a workflow
   never parses a bare stack trace. A crash that prints no line counts as exit 1 with an unknown state
   (1g addition).

Rules 2 to 5 are 1g additions; rule 1 is K5. The checks are in `adapters/contract_check.py`, which the
conformance suite imports.

## Idempotence and concurrency (K5)

- `release_id = <env>-<first 12 hex of the digest>`.
- `deploy` is idempotent per (env, digest): a rerun resumes from `status` and never starts a second rollout.
- One release in flight per env, enforced by the workflow concurrency group, not by the adapter.
- Exit 3 lets a workflow resume a long bake in a later job by calling `status` or `deploy` again.

## Declaration: `adapter.json` (K6)

`adapters/<kind>/adapter.json` declares:

| Key | Meaning |
|---|---|
| `contract_version` | `1` |
| `kind` | Runtime kind. A built-in kind matches the manifest `runtime.kind` enum; a project adapter (P15 step 4) uses its own lowercase name |
| `strategies` | Strategies the adapter can run (manifest `release.strategy` values) |
| `engines` | Engines it can run (manifest `release.engine` values) |
| `deploy_role_profile` | Name of the `modules/deploy-profile-<profile>` that grants exactly what the adapter calls (T8) |
| `egress_hosts` | Per verb, the host names the adapter contacts, as literal templates whose only placeholder is `{region}` |
| `max_step_seconds` | Longest single step; a workflow job timeout derives from it |

`egress_hosts` feeds the egress allowlist of the release job. A host not listed there is blocked.

## Conformance (K7)

`adapters/conformance/` runs every verb of every adapter against a stub on every PR. It is built in Phase 2. It
checks the declaration against `adapter.schema.json`, every printed line against `result.schema.json` and the
cross-field rules above, and the exit codes for success, failure, refusal and in-progress runs.

## Versioning (K8)

`contract_version` is `1`. A change to the contract is a new `contract_version` and a platform major bump (K8,
CLAUDE.md: an adapter contract change is a major bump). Inside v1 the schemas set `additionalProperties` to
false, so not even an optional input or result field may be added (1g addition).
