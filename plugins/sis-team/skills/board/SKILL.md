---
name: board
description: Show the status of the sis delivery GitHub Project board (cards per column, the Needs you queue) for this repo. Read-only. Use as /sis-team:board.
---

# /sis-team:board

Read-only. Shows where the cards are; it never moves, adds or comments.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/board.py" status
```

- `board.py` is built in its own sub-PR (ADR 0002 B11, sub-PR 1d). If the script is missing, say so and stop;
  do not call `gh project` yourself.
- It reads `SIS_BOARD_OWNER` and `SIS_BOARD_PROJECT` from `project.env` and refuses any other project. The
  project token is read from the Keychain by `board.py` alone (B16); never print or export it.
- Show the output as a table. Put the "Needs you" cards first, with their exact commands.
