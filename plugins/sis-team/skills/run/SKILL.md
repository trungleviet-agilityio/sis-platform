---
name: run
description: Build and verify one phase with the sis-team agents - build agents in parallel worktrees, merge, update docs, then verify agents in parallel, then stop at the checkpoint. Use as /sis-team:run <phase>.
argument-hint: <phase number>
disable-model-invocation: true
---

# /sis-team:run

Phase: `$ARGUMENTS` (ask for it if empty).

## 0. Preconditions

- The working tree is clean and on `main` (or a feature branch cut from it). Build agents branch their
  worktrees from the default branch, so anything uncommitted is invisible to them: if `git status` is not
  clean, stop and ask the owner to commit first.
- `docs/adr/` has an `accepted` ADR for this phase. If not, tell the owner to run `/sis-team:plan <phase>`.
- Create a feature branch `phase-<n>-<slug>` for the merged result.

## 1. Build (parallel)

Read the agent table in the repo's `CLAUDE.md`: it says which paths each build agent owns. Assign each
sub-ticket of the ADR's `## Build briefs` to the agent that owns its paths (`sis-team:backend-dev` or
`sis-team:devops-engineer`).

Spawn the needed agents in one message so they run in parallel. Give each a brief that stands alone: goal,
owned paths, the ADR decision IDs that are the spec, out of scope (the paths of the parallel sub-tickets),
done checks, and the report format (60 lines at most). Each works in its own worktree.

## 2. Merge

Merge each agent's worktree branch into the feature branch. Ownership is disjoint, so conflicts mean an agent
left its lane: stop and show the owner. Remove the worktrees afterwards.

## 3. Docs (you, not an agent)

You own the repo `README.md`, `CLAUDE.md` and `docs/**`; build agents never edit them. Module and plugin
READMEs are the build agents': check they exist and match the code, and send gaps back to them. After the
merge, update the docs this phase changed, from the ADR and the merged diff:

- `README.md`: setup steps, commands, variables and outputs that the phase added or changed.
- `docs/**` other than `docs/adr/`: runbooks or notes the phase calls for.
- Write only what the code does now. Every command must match a real script, target or workflow; no account
  IDs or emails.

Commit the docs separately (`docs(<scope>): ...`) so verify sees them in the diff.

## 4. Verify (parallel)

Spawn in one message: `sis-team:e2e`, `sis-team:reviewer`, `sis-team:security-reviewer`,
`sis-team:code-simplifier`. Give each the phase, the decision IDs and the list of changed files
(`git diff --name-only main...HEAD`).

## 5. Fix loop (at most 2 rounds)

- Critical/High security findings, reviewer bugs and new e2e failures go back to the owning build agent as a
  focused brief, then re-run only the verify agents that reported them. In round 2 the reviewers list every
  prior finding first as fixed, open or n/a. Docs drift findings you fix yourself.
- Medium/Low findings and simplifier suggestions are listed for the owner, not auto-fixed.
- After 2 rounds, stop and report what is still open.

## 6. Checkpoint (always stop here)

Commit on the feature branch (Conventional Commits). Then report:

1. What was built (files, one line each).
2. A verify table: agent, result, open findings.
3. The exact commands the owner runs by hand for this phase's checkpoint (from the ADR), such as
   `terraform apply`, GitHub environment setup, `git push` and PR. Never run them yourself.

Do not push or open a PR unless the owner asks.
