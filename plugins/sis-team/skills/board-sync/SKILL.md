---
name: board-sync
description: Move or add cards on the sis delivery GitHub Project board to match the phase lifecycle (Backlog, Planned, Ready, Building, Verify, Needs you, Done, Blocked). Changes the board, so only the owner starts it. Use as /sis-team:board-sync.
disable-model-invocation: true
---

# /sis-team:board-sync

Only the orchestrator moves cards; subagents never do (ADR 0002 B12).

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/board.py" status` and compare it with the phase state in the
   ADR and the open PRs.
2. List the changes you would make (add, move, comment), one line each, and run each with `--dry-run` first:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/board.py" <verb> ... --dry-run` prints the exact argv.
3. After the owner agrees, run the same commands without `--dry-run`.

- `board.py` is built in its own sub-PR (ADR 0002 B11, sub-PR 1d). If the script is missing, say so and stop.
- Use only the `board.py` verbs. Never call `gh project`, `gh api` or `gh project item-delete` directly, and
  never set `GH_TOKEN` or `GITHUB_TOKEN` (B16). Use `Blocked` only with a reason.
