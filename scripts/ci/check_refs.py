#!/usr/bin/env python3
"""Reference check: path-like tokens in the agent docs must resolve to something in the repo.

Usage: check_refs.py [--root DIR]

Scans inline backticked tokens in CLAUDE.md, .claude/rules/*.md, plugins/sis-team/agents/*.md and
plugins/sis-team/skills/**/SKILL.md (fenced code blocks are skipped). A token is path-like when it
has only path characters and either contains a slash or ends in a known file extension. Globs,
`<placeholders>`, commands with spaces, URLs and absolute paths are not paths, so they are skipped.

Each token is tried against the repo root, the file's own directory, the skill's directory,
plugins/sis-team/, intake/ and scripts/tf/. Exit 1 lists every miss as file:line. Exit 2 on a root
with nothing to scan. Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

# Exact tokens that do not resolve on purpose, each with its reason. A broken reference gets fixed.
ALLOWLIST = {
    "CLAUDE.local.md": "gitignored personal file, can be absent",
    "PLAN.md": "named only to forbid it",
    "PROGRESS.md": "named only to forbid it",
    "board.py": "planned (ADR 0002 B11), not built yet",
    "docs/diagrams/README.md": "created by the diagram skill in the repo it runs in",
    "docs/requirements.md": "exists in consumer repos and labs only",
    "platform.yaml": "the manifest of a consumer repo",
    "n/a": "not a path: the words 'not applicable'",
    "origin/main": "not a path: a git remote branch",
    "step-security/harden-runner": "not a path: a GitHub Action",
    "docs/diagrams/": "created by the diagram skill in the repo it runs in",
    "project.env": "consumer repos; here the orchestrator adds it at a checkpoint (ADR 0002 1d)",
    "locals.tf": "generic Terraform file name, one per module",
    "rules.py": "short name of intake/sis_intake/rules.py",
    "rules.json": "short name of intake/rules/rules.json",
    "icons.md": "short name of references/icons.md in the diagram skill",
    "check_drawio.py": "short name of scripts/check_drawio.py in the diagram skill",
}

PATH_CHARS_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
# At least one character before the extension, so a bare `.env` or `.drawio` is not a file name.
FILE_NAME_RE = re.compile(r"[^./]\.(md|py|sh|yml|yaml|json|toml|tf|hcl|env|txt|drawio|png)$")
INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def is_path_like(token: str) -> bool:
    if not PATH_CHARS_RE.match(token) or token.startswith(("/", "-")):
        return False
    # Local-only agent checkouts: gitignored, so absent in CI.
    if token.startswith(".claude/worktrees"):
        return False
    return "/" in token or FILE_NAME_RE.search(token) is not None


def scanned_files(root: Path) -> List[Path]:
    """The fixed set of docs. No pattern here descends into .claude/worktrees."""
    plugin = root / "plugins" / "sis-team"
    files = [root / "CLAUDE.md"]
    files += sorted((root / ".claude" / "rules").glob("*.md"))
    files += sorted((plugin / "agents").glob("*.md"))
    files += sorted((plugin / "skills").rglob("SKILL.md"))
    return [f for f in files if f.is_file()]


def tokens_in(text: str) -> Iterator[Tuple[int, str]]:
    """Yield (line number, token) for inline code outside fenced blocks."""
    fence = ""
    for number, line in enumerate(text.split("\n"), 1):
        match = FENCE_RE.match(line)
        if fence:
            # A fence closes on the same character, at least as long, with nothing after it.
            if match and match.group(1).startswith(fence) and not match.group(2).strip():
                fence = ""
            continue
        if match and "`" not in match.group(2):
            fence = match.group(1)
            continue
        for token in INLINE_CODE_RE.findall(line):
            yield number, token


def bases_for(root: Path, doc: Path) -> List[Path]:
    parts = doc.relative_to(root).parts
    bases = [root, doc.parent]
    if parts[:3] == ("plugins", "sis-team", "skills") and len(parts) > 4:
        bases.append(root.joinpath(*parts[:4]))
    bases += [root / "plugins" / "sis-team", root / "intake", root / "scripts" / "tf"]
    return bases


def resolves(token: str, root: Path, bases: Sequence[Path]) -> bool:
    exists = os.path.isdir if token.endswith("/") else os.path.exists
    for base in bases:
        candidate = os.path.normpath(base / token)
        inside = candidate == str(root) or candidate.startswith(str(root) + os.sep)
        if inside and exists(candidate):
            return True
    return False


def problems_in(root: Path, doc: Path) -> List[str]:
    rel = doc.relative_to(root).as_posix()
    bases = bases_for(root, doc)
    return [
        f"{rel}:{number}: reference `{token}` does not resolve"
        for number, token in tokens_in(doc.read_text(encoding="utf-8"))
        if is_path_like(token) and token not in ALLOWLIST and not resolves(token, root, bases)
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check path references in the agent docs.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    docs = scanned_files(root)
    if not docs:
        print(f"check_refs: nothing to scan under {root}", file=sys.stderr)
        return 2
    problems = [problem for doc in docs for problem in problems_in(root, doc)]
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"check_refs: {len(docs)} files, every reference resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
