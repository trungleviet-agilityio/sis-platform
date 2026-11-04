# Example consumer repository

The smallest layout a project repository needs to use sis-platform (ADR 0002, L1 to L4). Copy it, then replace
the names, SHAs and IDs. Nothing here is a real account, repository or release.

| Path | Purpose |
|---|---|
| `platform.yaml` | The manifest, the only source of release behavior. Valid under the current validator |
| `platform.lock` | The release pin: `version`, `release_sha`, `workflow_sha` and `trusted_workflow_shas` (N and N-1). The SHAs here are placeholders; the intake or bump step fills in the real ones |
| `project.env` | Non-secret project identity, checked against `project.prefix` |
| `.claude/settings.json` | Pins the `sis-platform` plugin marketplace to the lock `version` (L4) |
| `infra/bootstrap/` | Root that owns the provider and backend and calls `account-bootstrap`. The example calls the module by local path; a real consumer uses the `git::` source pinned to `release_sha` (see the comment in `main.tf`) |
| `.github/workflows/` | Thin callers of the reusable workflows. Not part of this layout yet (sub-PR 1f-2) |

No account ID, email or state bucket name is committed. They live in `accounts/<env>.tfvars` and
`accounts/<env>.backend.hcl`, which `.gitignore` already blocks (`*.tfvars`, `*.tfbackend`).

## Checks

```sh
# Offline P9 check: lock schema, platform.yaml version, workflow and module pins, plugin pin.
python3 scripts/platform/check_lock.py examples/consumer

# Also against a clone of sis-platform: tag, ancestry, closure and the trusted SHAs (needs network).
python3 scripts/platform/check_lock.py examples/consumer --remote
```

`--remote` fails on this example by design: its SHAs are placeholders, not a real release.
