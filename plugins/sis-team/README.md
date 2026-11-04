# sis-team

Claude Code agent team for sis-platform and the repos that use it. A solution architect settles each phase's
design in an ADR; two build agents (`backend-dev`, `devops-engineer`) work in their own git worktrees with
TDD; four verify agents (`e2e`, `reviewer`, `security-reviewer`, `code-simplifier`) check the result in
parallel and never edit files. Path ownership comes from the repo's `CLAUDE.md`.

A `PreToolUse` guard hook (`scripts/guard.py`, stdlib, system `python3` 3.9) keeps a human in charge of the
risky steps. It blocks:

- `terraform apply`/`destroy`/`import`, state mutation, Secrets Manager value access and IAM writes;
- PR merges, releases (`gh release`, pushes of `v*` tags, `--tags`), workflow dispatch, `gh api` writes, `gh project item-delete`, and pushes to `main`;
- reads of secret files, and credential literals in a command (`AKIA`, `ghp_`, `github_pat_`, PEM header);
- `Edit`/`Write` outside the repo or worktree, and `rm -r` outside the repo root (extra directories can be
  allowed with `SIS_GUARD_EXTRA_ROOTS`, a `:` separated list);
- a Bash command that reads the `sis-board-token` Keychain item or sets `GH_TOKEN`/`GITHUB_TOKEN` inline.

The guard is quote and shell aware: it recurses into `bash -c`, `eval`, `python -c`, `$(...)` and `xargs`,
ignores quoted text and heredoc bodies, and fails closed (exit 2) on an internal error or malformed hook input. A shell fed by a pipe,
process substitution, stdin or file redirect is blocked; a literal here-string or heredoc is scanned. `Edit`/`Write` also
stay allowed in `/tmp/claude-<uid>` (the Claude scratchpad parent) when that directory is private to the user.
Edit and Write on the guard itself and on `.claude/settings.json` are allowed on purpose (ADR 0002 S7,
accepted): sessions load the guard from the last tag and the owner reviews every PR.

Some guard ideas are adapted from super-board (https://github.com/EricTechPro/super-board, MIT). Tests:
`python3 -m unittest discover -s plugins/sis-team/scripts -p 'test_*.py'` (run by `make test`).

Install in a project (the marketplace is this repo; pin it to a release tag with `ref` in
`extraKnownMarketplaces`, see ADR 0002 L4):

```
/plugin marketplace add trungleviet-agilityio/sis-platform
/plugin install sis-team@sis-platform
```

Commands: `/sis-team:plan <phase>`, `/sis-team:run <phase>`, `/sis-team:close <phase> [checkpoint]`,
`/sis-team:review [PR]`, `/sis-team:team` (agent roster table from the agent files),
`/sis-team:diagram <topic>` (draw.io AWS diagrams, checked and exported to PNG), `/sis-team:board` (read-only
board status) and `/sis-team:board-sync` (card moves). `plan`, `run`, `close` and `board-sync` have side
effects, so only the user can start them. `board.py`, behind both board skills, ships in a later sub-PR.
Decisions: ADR 0002, section S.
