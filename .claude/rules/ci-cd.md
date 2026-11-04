---
paths:
  - ".github/**"
  - ".claude-plugin/**"
---

# CI/CD rules

- Every `uses:` is pinned to a 40-hex commit SHA with a `# vX.Y.Z` comment, looked up live. Local `./` actions are
  the only exception.
- Every workflow has top-level `permissions: {}` and grants per job only what it needs. `id-token: write` only on
  a job whose steps assume a role or print OIDC claims (ADR 0002 H2).
- Triggers: `pull_request`, `push` to `main`, or `workflow_call` (reusable workflows use `workflow_call` only).
  The `consumer` guard profile (`examples/consumer`) also allows `workflow_dispatch` with inputs `env` (choice),
  `sha` or `digest`, and `schedule` (ADR 0002 H4, Amendment C).
- Reusable workflows set `defaults.run.shell: bash` (pipefail), refuse unexpected events and refs in their first
  step (AA3), and list sparse-checkout patterns equal to `scripts/release/closure.txt` (`scripts/ci/check_sparse.py`).
  Any file they run from `.platform/` must be in the closure.
- harden-runner is the first step of every job. Credentialed jobs use `egress-policy: block` with exact hosts, no
  wildcard families such as `*.execute-api` (ADR 0001 A9).
- A reusable workflow's path is part of the consumers' OIDC trust (`job_workflow_ref`, ADR 0001 O2): renaming or
  moving one is a major version bump.
- `scripts/ci/selftest.sh` must still pass (`make lint`).
