---
paths:
  - "scripts/**"
  - "Makefile"
---

# scripts and Makefile rules

- Bash scripts run on macOS `/bin/bash` 3.2 and on CI bash 5: no associative arrays, no `mapfile`, no `${var,,}`.
  Start with `set -euo pipefail` and pass `shellcheck -x`.
- A guard or check script gets a self-test that asserts the specific error message, not only a non-zero exit.
- The Makefile stays GNU Make 3.81 compatible. Never add an `apply` or `destroy` target.
