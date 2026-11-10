# Example consumer repository

The smallest layout a project repository needs to use sis-platform (ADR 0002, L1 to L4). Copy it, then replace
the names, SHAs and IDs. Nothing here is a real account, repository or release.

| Path | Purpose |
|---|---|
| `platform.yaml` | The manifest, the only source of release behavior. Valid under the current validator |
| `platform.lock` | The release pin: `version`, `release_sha`, `workflow_sha` and `trusted_workflow_shas` (N and N-1). The SHAs here are placeholders; the intake or bump step fills in the real ones |
| `project.env` | Non-secret project identity. Every reusable workflow's resolve step fails unless `SIS_PROJECT_PREFIX` equals `project.prefix` (M7) |
| `.claude/settings.json` | Pins the `sis-platform` plugin marketplace to the lock `version` (L4) |
| `infra/bootstrap/` | Root that owns the provider and backend and calls `account-bootstrap`. The example calls the module by local path; a real consumer uses the `git::` source pinned to `release_sha` (see the comment in `main.tf`) |
| `infra/envs/<env>/` | The env roots the reusable plan and apply workflows run (`dev` and `prod` here, one `terraform_data` each) |
| `.github/workflows/` | Thin callers of the reusable workflows, pinned to `workflow_sha` with the lock `version` as the comment |

No account ID, email or state bucket name is committed. They live in `accounts/<env>.tfvars` and
`accounts/<env>.backend.hcl`, which `.gitignore` already blocks (`*.tfvars`, `*.tfbackend`).

## Callers

| Workflow | Trigger | Calls | Secret passed |
|---|---|---|---|
| `terraform.yml` | pull request: plan `dev` with a sticky comment; push to `main`: apply `dev`; dispatch `env`: apply that env | `reusable-terraform-plan.yml`, `reusable-terraform-apply.yml` | plan: repo secret `AWS_ACCOUNT_ID_DEV`; apply: environment secret `AWS_ACCOUNT_ID` |
| `platform-check.yml` | every pull request (make it a required check) and weekly | `reusable-platform-check.yml` (`check_lock.py --remote`) | none |
| `oidc-smoke.yml` | dispatch on `main` (checkpoint step 4a): prints the OIDC claims, no AWS call | `reusable-oidc-smoke.yml`, `check: claims` | environment secret `AWS_ACCOUNT_ID` |
| `oidc-negative.yml` | dispatch on `main` (checkpoint step 7): the apply and deploy roles must answer AccessDenied | `reusable-oidc-smoke.yml`, `check: negative` | environment secret `AWS_ACCOUNT_ID` |

Secrets (O13): each GitHub environment (`dev`, `prod`) holds the environment secret `AWS_ACCOUNT_ID`; the repo holds
`AWS_ACCOUNT_ID_<ENV>` (`AWS_ACCOUNT_ID_DEV`, `AWS_ACCOUNT_ID_PROD`) for plans, which run without an environment. The
caller jobs set no `environment` key and never use `secrets: inherit`.

The first push to `main` after the callers land queues a `dev` apply that waits for the environment approval.
Reject it until the bootstrap exists and checkpoint step 8 is reached; an approved apply before that fails at the
role assumption.

## Env root contract (`infra/envs/<env>/`)

- `terraform { backend "s3" {} }` with nothing inside: the workflow composes bucket, key, region and the S3 lock at
  run time (T3), because the bucket name holds the account ID.
- A committed `.terraform.lock.hcl` (`terraform providers lock -platform=linux_amd64 -platform=darwin_arm64`):
  init runs with `-lockfile=readonly`, and only `registry.terraform.io/hashicorp/*` providers install.
- `variable "platform"`: the workflow passes the M7 env slice with `-var-file` from the runner's temp dir.
- Module sources are local or sis-platform pinned to `release_sha`.

## Checks

```sh
# Offline P9 check: lock schema, platform.yaml version, workflow and module pins, plugin pin.
# --platform-checkout is only for this example, which lives inside the sis-platform checkout and
# calls ../../../../modules/... by path: local sources may leave examples/consumer but not the checkout.
# A real consumer repository runs it without the flag, and then no local source may leave the repo.
python3 scripts/platform/check_lock.py examples/consumer --platform-checkout

# Also against a clone of sis-platform: tag, ancestry, closure and the trusted SHAs (needs network).
python3 scripts/platform/check_lock.py examples/consumer --remote
```

The module-source rule is a text and JSON scan of `*.tf`, `*.tf.json`, `*.tofu` and `*.tofu.json`. It is not the
last line of defense: the reusable plan and apply workflows run `scripts/tf/resolved-sources.sh <dir> <data dir>
<release_sha from platform.lock>` after each `terraform init`, the first time before any credential, and it fails
closed on what Terraform actually resolved.

`--remote` fails on this example by design: its SHAs are placeholders, not a real release.
