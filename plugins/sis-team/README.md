# sis-team

Claude Code agent team for sis-platform and the repos that use it. A solution architect settles each phase's
design in an ADR; two build agents (`backend-dev`, `devops-engineer`) work in their own git worktrees with
TDD; four verify agents (`e2e`, `reviewer`, `security-reviewer`, `code-simplifier`) check the result in
parallel and never edit files. Path ownership comes from the repo's `CLAUDE.md`.

A `PreToolUse` guard hook (`scripts/guard.py`, stdlib, system `python3` 3.9) keeps a human in charge of the
risky steps. It blocks:

- `terraform apply`/`destroy`/`import`, state mutation, Secrets Manager value access and IAM writes;
- PR merges, workflow dispatch, `gh api` writes, `gh project item-delete`, and pushes to `main`;
- reads of secret files, and credential literals in a command (`AKIA`, `ghp_`, `github_pat_`, PEM header);
- `Edit`/`Write` outside the repo or worktree, and `rm -r` outside the repo root (extra directories can be
  allowed with `SIS_GUARD_EXTRA_ROOTS`, a `:` separated list);
- a Bash command that reads the `sis-board-token` Keychain item or sets `GH_TOKEN`/`GITHUB_TOKEN` inline.

Some guard ideas are adapted from super-board (https://github.com/EricTechPro/super-board, MIT). Tests:
`python3 -m unittest discover -s plugins/sis-team/scripts -p 'test_*.py'` (run by `make test`).

Commands: `/sis-team:plan <phase>`, `/sis-team:run <phase>`, `/sis-team:close <phase> [checkpoint]`,
`/sis-team:review [PR]`, `/sis-team:team` (agent roster table from the agent files),
`/sis-team:diagram <topic>` (draw.io AWS diagrams, checked and exported to PNG), `/sis-team:board` (read-only
board status) and `/sis-team:board-sync` (card moves). `plan`, `run`, `close` and `board-sync` have side
effects, so only the user can start them. `board.py`, behind both board skills, ships in a later sub-PR.
Decisions: ADR 0002, section S.
